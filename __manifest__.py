{
	'name': 'APS SIS Resources',
	'version': '18.0.1.0.0',
	'category': 'Tools',
	'summary': 'Manage APS resources and types (URLs, descriptions).',
	'description': 'APS - Academic Positioning System. Helps to track student progress. It will work with  EduCat SIS',
	'author': 'APS',
	'license': 'LGPL-3',
	'depends': ['base'],
	'data': [
		'security/ir.model.access.csv',
		'views/aps_resources_views.xml',
	],
	'installable': True,
	'application': False,
}
