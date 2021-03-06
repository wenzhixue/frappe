# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
import frappe, os

from frappe.website.utils import can_cache, delete_page_cache
from frappe.model.document import get_controller

def get_page_context(path):
	page_context = None
	if can_cache():
		page_context_cache = frappe.cache().hget("page_context", path) or {}
		page_context = page_context_cache.get(frappe.local.lang, None)

	if not page_context:
		page_context = make_page_context(path)
		if can_cache(page_context.no_cache):
			page_context_cache[frappe.local.lang] = page_context
			frappe.cache().hset("page_context", path, page_context_cache)

	return page_context

def make_page_context(path):
	context = resolve_route(path)
	if not context:
		raise frappe.DoesNotExistError

	context.doctype = context.ref_doctype
	context.title = context.page_title
	context.pathname = frappe.local.path

	return context

def resolve_route(path):
	"""Returns the page route object based on searching in pages and generators.
	The `www` folder is also a part of generator **Web Page**.

	The only exceptions are `/about` and `/contact` these will be searched in Web Pages
	first before checking the standard pages."""
	if path not in ("about", "contact"):
		context = get_page_context_from_template(path)
		if context:
			return context
		return get_page_context_from_doctype(path)
	else:
		context = get_page_context_from_doctype(path)
		if context:
			return context
		return get_page_context_from_template(path)

def get_page_context_from_template(path):
	found = filter(lambda p: p.page_name==path, get_pages())
	return found[0] if found else None

def get_page_context_from_doctype(path):
	generator_routes = get_page_context_from_doctypes()
	if path in generator_routes:
		route = generator_routes[path]
		return frappe.get_doc(route.get("doctype"), route.get("name")).get_route_context()

def clear_sitemap():
	delete_page_cache("*")

def get_page_context_from_doctypes():
	routes = frappe.cache().get_value("website_generator_routes")
	if not routes:
		routes = {}
		for app in frappe.get_installed_apps():
			for doctype in frappe.get_hooks("website_generators", app_name = app):
				condition = ""
				route_column_name = "page_name"
				controller = get_controller(doctype)
				meta = frappe.get_meta(doctype)

				if meta.get_field("parent_website_route"):
					route_column_name = """concat(ifnull(parent_website_route, ""),
						if(ifnull(parent_website_route, "")="", "", "/"), page_name)"""

				if controller.website.condition_field:
					condition ="where {0}=1".format(controller.website.condition_field)

				for r in frappe.db.sql("""select {0} as route, name, modified from `tab{1}`
						{2}""".format(route_column_name, doctype, condition), as_dict=True):
					routes[r.route] = {"doctype": doctype, "name": r.name, "modified": r.modified}

		frappe.cache().set_value("website_generator_routes", routes)

	return routes

def get_pages():
	pages = frappe.cache().get_value("_website_pages")
	if not pages:
		pages = []
		for app in frappe.get_installed_apps():
			app_path = frappe.get_app_path(app)
			path = os.path.join(app_path, "templates", "pages")
			if os.path.exists(path):
				for fname in os.listdir(path):
					fname = frappe.utils.cstr(fname)
					page_name, extn = fname.rsplit(".", 1)
					if extn in ("html", "xml", "js", "css"):
						route_page_name = page_name if extn=="html" else fname

						# add website route
						route = frappe._dict()
						route.page_or_generator = "Page"
						route.template = os.path.relpath(os.path.join(path, fname), app_path)
						route.name = route.page_name = route_page_name
						controller_path = os.path.join(path, page_name.replace("-", "_") + ".py")

						if os.path.exists(controller_path):
							controller = app + "." + os.path.relpath(controller_path,
								app_path).replace(os.path.sep, ".")[:-3]
							route.controller = controller

							for fieldname in ("page_title", "no_sitemap"):
								try:
									route[fieldname] = frappe.get_attr(controller + "." + fieldname)
								except AttributeError:
									pass

						pages.append(route)

		frappe.cache().set_value("_website_pages", pages)
	return pages

def process_generators(func):
	for app in frappe.get_installed_apps():
		for doctype in frappe.get_hooks("website_generators", app_name = app):
			order_by = "name asc"
			condition_field = None
			controller = get_controller(doctype)

			if hasattr(controller, "condition_field"):
				condition_field = controller.condition_field
			if hasattr(controller, "order_by"):
				order_by = controller.order_by

			val = func(doctype, condition_field, order_by)
			if val:
				return val
