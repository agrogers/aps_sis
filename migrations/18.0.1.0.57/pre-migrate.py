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

    cr.execute(
        "ALTER TABLE aps_resources ADD COLUMN IF NOT EXISTS ai_toc boolean DEFAULT false"
    )
    cr.execute(
        "ALTER TABLE aps_resources ADD COLUMN IF NOT EXISTS ai_summary boolean DEFAULT false"
    )
    cr.execute(
        "ALTER TABLE aps_resources ADD COLUMN IF NOT EXISTS ai_analysis boolean DEFAULT false"
    )
    cr.execute(
        "ALTER TABLE aps_resources ADD COLUMN IF NOT EXISTS ai_table_of_results boolean DEFAULT false"
    )
    _logger.info(
        "18.0.1.0.57 migration: ensured ai_toc, ai_summary, ai_analysis, "
        "ai_table_of_results columns exist on aps_resources"
    )
