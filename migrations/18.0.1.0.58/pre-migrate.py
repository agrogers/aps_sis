"""
Pre-migration 18.0.1.0.58: add new columns to aps_award_vote_round for the
expanded voting configuration:

Eligible Voters / Candidates tab visibility toggles:
  voter_show_staff, voter_show_levels, voter_show_categories, voter_show_departments
  candidate_show_levels, candidate_show_categories, candidate_show_students, candidate_show_departments

Ineligible Candidates:
  ineligible_show_people (boolean toggle to reveal the People list)
  ineligible_candidates  (jsonb — stores exclude_voter flag and partner_ids)
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — ORM creates columns on init

    # Eligible Voters tab toggles
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS voter_show_staff boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS voter_show_levels boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS voter_show_categories boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS voter_show_departments boolean DEFAULT false")

    # Eligible Candidates tab toggles
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS candidate_show_levels boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS candidate_show_categories boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS candidate_show_students boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS candidate_show_departments boolean DEFAULT false")

    # Ineligible Candidates
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS ineligible_show_people boolean DEFAULT false")
    cr.execute("ALTER TABLE aps_award_vote_round ADD COLUMN IF NOT EXISTS ineligible_candidates jsonb")

    _logger.info(
        "18.0.1.0.58 migration: added department toggle, ineligible_candidates "
        "and section-visibility columns to aps_award_vote_round"
    )
