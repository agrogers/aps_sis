from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    env['ai_prompts'].sudo().ensure_default_targeted_feedback_prompt()