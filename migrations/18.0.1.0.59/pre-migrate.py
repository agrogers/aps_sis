"""
Pre-migration 18.0.1.0.59:

Changes:
- voter_show_staff label renamed to 'People' (allows both staff and students as voters)
- eligible_voter_partner_ids label renamed to 'People'
- voter wizard domain restriction removed (staff-only domain dropped)
- _collect_eligible_voter_partners now also includes students by level
- New rule: rule_limit_to_voter_year_level (stored in rules JSON — no new DB column)
- 'Candidate Restrictions' section moved from Rules tab to Ineligible Candidates tab
- rule_limit_to_voter_year_level toggle added to Ineligible Candidates tab

No new database columns are needed (the new rule is stored in the existing rules JSONB field).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM creates columns on init

    _logger.info(
        "18.0.1.0.59 migration: no schema changes required — "
        "rule_limit_to_voter_year_level stored in existing rules JSONB column"
    )
