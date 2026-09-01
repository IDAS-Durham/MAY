import logging

logger = logging.getLogger(__name__)

class _ReportingMixin:
        def log_allocation_summary(self, world, eligible_count: int = None):
            """Log summary statistics of allocation."""
            total_people = len(world.people)
            allocated = self.owner.allocated_this_run

            logger.info(f"Allocation summary for {self.owner.venue_type}:")
            logger.debug(f"  - Total people in world: {total_people}")
            if eligible_count is not None:
                logger.info(
                    f"  - Eligible people identified: {eligible_count} "
                    f"({eligible_count / total_people * 100:.1f}%)"
                )
                logger.info(
                    f"  - Allocated this run: {allocated} "
                    f"({allocated / eligible_count * 100:.1f}%)"
                    if eligible_count > 0
                    else f"  - Allocated this run: {allocated}"
                )
            else:
                logger.info(f"  - Allocated this run: {allocated}")

