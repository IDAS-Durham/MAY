"""
Test script for relationship rules configuration.

This script verifies that relationship rules are properly configured and loaded.
"""

import logging
import os
import yaml
from residence.relationship_rules import RelationshipRulesValidator
from residence.household import AgeCategory

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger("test")

def main():
    logger.info("=" * 60)
    logger.info("RELATIONSHIP RULES CONFIGURATION TEST")
    logger.info("=" * 60)

    # Load age categories from households config
    logger.info("\n1. Loading age categories from households_config.yaml...")
    config_path = "data/households/households_config.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    age_categories = []
    for cat_config in config['age_categories']:
        cat = AgeCategory(
            name=cat_config['name'],
            symbol=cat_config['symbol'],
            min_age=cat_config['min_age'],
            max_age=cat_config['max_age']
        )
        age_categories.append(cat)

    logger.info(f"✓ Loaded {len(age_categories)} age categories:")
    for cat in age_categories:
        logger.info(f"  - {cat}")

    # Load relationship rules
    logger.info("\n2. Loading relationship rules...")
    rules_path = "data/households/relationship_rules.yaml"

    if not os.path.exists(rules_path):
        logger.error(f"✗ Relationship rules file not found: {rules_path}")
        return

    validator = RelationshipRulesValidator(
        age_categories=age_categories,
        config_file=rules_path
    )

    if validator.enabled:
        logger.info("✓ Relationship rules are ENABLED")
        logger.info(f"  Loaded {len(validator.rules)} rules")
        logger.info("")

        for rule in validator.rules:
            logger.info(f"  Rule: {rule.name}")
            logger.info(f"    Patterns: {rule.patterns}")
            logger.info(f"    Roles: {list(rule.roles.keys())}")
            logger.info(f"    Selection order: {rule.selection_order}")
            logger.info(f"    Constraints: {len(rule.constraints)} defined")
            logger.info("")

        # Show selection strategy
        logger.info("3. Selection Strategy:")
        logger.info(f"  Max attempts: {validator.selection_strategy.get('max_attempts', 50)}")
        logger.info(f"  Use best candidate: {validator.selection_strategy.get('use_best_candidate', True)}")
        logger.info(f"  Penalty mode: {validator.selection_strategy.get('penalty_mode', 'squared')}")
        logger.info(f"  Track statistics: {validator.track_statistics}")

    else:
        logger.warning("✗ Relationship rules are DISABLED")
        logger.warning("  Check 'enabled: true' in relationship_rules.yaml")

    logger.info("\n" + "=" * 60)
    logger.info("TEST COMPLETE")
    logger.info("=" * 60)

    if validator.enabled:
        logger.info("\n✓ Relationship rules are configured and ready!")
        logger.info("\nTo see the rules in action, run:")
        logger.info("  python create_world.py")
        logger.info("\nThe allocation will automatically:")
        logger.info("  1. Select people according to role selection order")
        logger.info("  2. Apply numerical attribute difference constraints (e.g., age, income)")
        logger.info("  3. Match compatible pairs based on categorical and numerical attributes")
        logger.info("  4. Use best-candidate fallback when needed")
        logger.info("\nStatistics will be printed at the end showing:")
        logger.info("  - Pair types (same-category vs different-category)")
        logger.info("  - Numerical attribute differences between partners")
        logger.info("  - Best-candidate selections count")
    else:
        logger.warning("\n✗ Relationship rules are disabled")
        logger.warning("  Set 'enabled: true' in data/households/relationship_rules.yaml")

if __name__ == "__main__":
    main()
