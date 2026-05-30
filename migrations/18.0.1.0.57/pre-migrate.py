"""
Pre-migration 18.0.1.0.57: add ai_toc, ai_summary, ai_analysis, and
ai_table_of_results boolean columns to the aps_resources table.

These columns default to False and represent the new section-based prompt
shortcut toggles on the AI Instructions tab.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM creates columns on init

    new_columns = [
        'ai_toc',
        'ai_summary',
        'ai_analysis',
        'ai_table_of_results',
    ]
    for col in new_columns:
        cr.execute(
            f"ALTER TABLE aps_resources ADD COLUMN IF NOT EXISTS {col} boolean DEFAULT false"
        )
        _logger.info("18.0.1.0.57 migration: ensured column aps_resources.%s exists", col)
