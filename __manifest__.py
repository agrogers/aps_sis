{
	'name': 'APS SIS Resources',
	'version': '18.0.1.0.1',
	'category': 'Tools',
	'summary': 'Manage APS resources and types (URLs, descriptions).',
	'description': 'APS - Academic Positioning System. Helps to track student progress. It will work with  EduCat SIS',
	'author': 'APS',
	'license': 'LGPL-3',
	'depends': ['base', 'openeducat_core', 'openeducat_fees', 'web'],
	'data': [
		'security/ir.model.access.csv',
		'views/aps_resources_views.xml',
		'views/aps_tasks_views.xml',
		'views/op_program_level_views.xml',
		'views/op_course_views.xml',
		'views/op_subject_views.xml',
		'views/op_faculty_views.xml',
		'views/res_partner_views.xml',
		'views/aps_sis_menu.xml',
		'views/op_student_course_views.xml',
	],
	'assets': {
		'web.assets_backend': [
			'aps_sis/static/src/js/url_icon_widget.js',
		],
	},
	'assets': {
		'web.assets_backend': [
			'aps_sis/static/src/js/url_icon_widget.js',
		],
	},
	'installable': True,
	'application': False,
}
