# Household Distributor Documentation

## Overview

Everything is kicked off by `execute_allocation_strategy` in `allocation_strategy.py`

There we read step by step what type of step they are:

- **household**: First round of households
- **venue**: Venues such as boarding schools, care homes, dorms, etc
- **household excess**: Add remaining people to households that have expandable compositions (>=)
  - "Add these specific people to matching households"
- **household promotion**: Change existing households to expandable compositions, e.g. giving couples kids (0 0 2 0 -> >=0 >=0 2 0)
  - "Transform these households to accept specific types of people"
- **household overflow**: Distributes people balancedly across selected patterns (this is good to get rid of all remaining people)
  - "Put everyone somewhere, size doesn't matter"

## Feature Comparison Matrix

| Feature | household | household_excess | household_promotion | household_overflow |
|---------|-----------|------------------|---------------------|-------------------|
| **Creates new households?** | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **Respects max size?** | ✅ Yes | ✅ Yes | ⚠️ Controlled | ❌ No |
| **Adds to existing?** | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Allocates ALL remaining?** | ❌ No | ❌ No | ⚠️ Rule-dependent | ✅ Yes |
| **Pattern biasing?** | ❌ No | ❌ No | ❌ No | ✅ Yes |
| **Control mechanism** | Patterns & max households | Constraints & distributions | Promotion rules | Balanced distribution |
| **Unique feature** | Initial household creation | Targeted additions with limits | Rule-based promotion | Ignores size constraints |
| **Primary use case** | Create base households | Add specific people to households | Transform households to accept more | Sweep up all remaining |

---

## Household

This is done in `_execute_household_step` in `allocation_strategy.py`

We take the pattern and if the pattern used has an 'assumption' we also save that (>=2 >=0 2 0 is assumed to be 2 0 2 0)

Then we do `distribute_household_round` that is in `household_distributor.py` (which is then sent to `household_round_distributor.py`) which is a parameter we passed to the method.

Here we have some settings like `allocate_flexible`. This is only for households that are mostly flexible like 0 >=0 >=0 >=0, and we randomly allocate people in a distributed balanced manner (we use `_calculate_balanced_distribution`)

### distribute_households_round

The main household allocation workhorse

**The gist:** Creates a batch of households in one go, with a bunch of knobs you can turn to control exactly what gets allocated.

#### How it works:

1. **Set up the round:** Logs the start, refreshes person pools if needed (to exclude already allocated people)
2. **Loop through all geo units:**
   - For each geo unit, look at all the household types (patterns) needed
   - Filter to only allocate certain patterns if you specified a pattern_filter
   - Apply "assumptions" if you have them (like "when census says '0 >=0 0 0', actually use '0 2 0 0'")
3. **Allocate each household:**
   - If using flexible allocation (allocate_flexible=True), pre-calculates balanced sizes for all households
   - For each household needed, calls [`_attempt_with_demotion`](#_attempt_with_demotion) (with rules) or [`_allocate_household_with_rules`](#_allocate_household_with_rules) (without demotion)
   - Tracks whether demotion was used
   - Stops if you hit max_households limit
4. **Track and log everything:**
   - Counts successes, failures, demotions
   - Shows how many households were requested vs created
   - Returns detailed stats dict

#### Key features:

- **pattern_filter**: Only allocate specific patterns (e.g., just couples, just families with kids)
- **pattern_assumptions**: Override census patterns with your assumptions (census obfuscation workaround)
- **max_households**: Cap how many to create this round
- **allocate_flexible**: Use balanced distribution instead of minimum
- **rule_name**: Apply relationship rules for realistic ages/relationships
- **demotion_rules**: Switch rules when patterns get demoted

**Returns:** Stats dict with household counts, people allocated, etc.

**Basically:** "The main allocation engine - loops through all geo units and creates households according to census data, with tons of options to control filtering, assumptions, size limits, and relationship rules. Tracks everything and gives you detailed stats at the end."

### _attempt_with_demotion

This basically the "try, try again" method for household allocation.

**The gist:** You want to make a household with a certain pattern (like "2 kids + 2 adults"), but what if you don't have enough kids? This method doesn't just give up – it gets creative.

#### How it works:

- **First attempt:** Tries to allocate with your original pattern (with [`_allocate_household_with_rules`](#_allocate_household_with_rules))
- **If that fails** (say, not enough kids available), it "demotes" the pattern by reducing the count of whatever category caused the problem
- **Then it tries again** with this smaller pattern
- **Keeps doing this** up to max_attempts times
- Each time it demotes, it makes the household pattern smaller/simpler

**The smart part:** It does "intelligent demotion" - meaning if you failed because you ran out of kids, it'll specifically reduce the kid count. It even checks how many people are actually available in that category and jumps straight to that count (demote_to_count) instead of going one-by-one (demote_once).

**Safety checks:** It won't let you end up with a household that's too small (checks against min_household_size config), and validates against any demotion rules you've set up (validate_against_rules).

**Rule switching:** If you've configured demotion_rules, it can even switch to a different relationship rule when the pattern changes (like going from a "family with kids" rule to a "couple" rule after demoting away the kids).

**Basically:** "Keep trying with smaller household patterns until something works or we hit rock bottom."

### _allocate_household_with_rules

**The gist:** This is the "fancy" household allocation that respects relationship rules (like making sure adults are old enough to be parents, or finding compatible couples).

#### How it works:

- If you don't pass a rule_name, it just bails out to the simple allocation (no constraints) ([`_allocate_household`](#_allocate_household))
- If you DO pass a rule name, it looks up that rule from the relationship_rules validator
- Then it goes through the rule's selection order (e.g., pick kids first, then find adults old enough to be their parents)
- Uses a backtracking algorithm to try different combinations if the first attempt fails ([`_select_roles_with_backtracking`](#_select_roles_with_backtracking)) which applies constraints as it goes: age differences between roles, couple matching, etc.

**Returns:** Either a fully-formed household with everyone assigned, or (None, failed_category_idx) if it couldn't make it work.

**Basically:** "Build a household while respecting real-world relationship constraints like age gaps and compatible partners, and be smart about retrying when things don't work out."

### _allocate_household

The simple household maker (no relationship rules)

**The gist:** Creates a household by grabbing people from pools to match a pattern. This is the "dumb" version that doesn't care about relationships, ages, or anything fancy - just matches the numbers.

#### How it works:

1. **Logs the attempt:** Sets up detailed logging for this allocation (geo unit, pattern, constraints)
2. **Pick an allocation strategy:**

   **[`_allocate_balanced_distribution`](#_allocate_balanced_distribution)**
   - Balanced distribution mode (if allocate_flexible=True AND target_size is set):
     - Uses proportional allocation to hit a specific target household size
     - Spreads extra people across flexible categories proportionally

   **[`_allocate_sequential`](#_allocate_sequential)**
   - Sequential mode (default):
     - Goes through categories in order
     - Takes minimum required for each, or randomly allocates to flexible categories
     - Simpler, less sophisticated

3. **Check if it's possible:**
   - Both strategies return a list of (category_idx, count) selections
   - If any category doesn't have enough people, returns failure with that category index
4. **Actually grab the people:**
   - Takes the first N people from each category's pool (already shuffled)
   - Removes them from the pools
   - Logs who got selected
5. **Create the household:**
   - Makes a new Household object
   - Adds all selected people as residents
   - Marks them as allocated
   - Stores original pattern and actual pattern (in case it was demoted)

**Returns:** (Household, None) if successful, or (None, failed_category_idx) if it couldn't find enough people.

**Key point:** This is called by [`_allocate_household_with_rules`](#_allocate_household_with_rules) when NO rule is specified, or as a fallback. It's the basic "just match the pattern numbers" allocation without any relationship validation.

**Basically:** "The no-frills household creator. Just grab people to match the pattern's numbers - don't worry about whether a 20-year-old 'adult' makes sense as a parent to a 15-year-old 'kid'. That's what the rules version is for."

### _allocate_balanced_distribution

The proportional household filler

**The gist:** When you have flexible categories (like ">=2 young adults") and want households to hit a specific target size, this figures out how to distribute people proportionally across those flexible categories instead of just taking minimums or randomly allocating.

#### How it works:

**First pass - separate fixed from flexible:**
1. Goes through all categories in the pattern
2. Fixed categories (exact counts like "2 kids"): Allocates exactly that number immediately
3. Flexible categories (like ">=1 adults"): Sets aside for proportional allocation
4. Tracks the "fixed total" - how many people are already spoken for

**Second pass - proportional allocation:**
1. Calculates remaining capacity: target_size - fixed_total
2. For each flexible category, allocates proportionally based on availability
   - If a category has 60% of available flexible people, it gets 60% of remaining slots
   - Example: Need to allocate 10 more people, category has 30 available out of 50 total → gets 6 slots
3. Ensures each category gets at least its minimum and doesn't exceed availability

**Remainder distribution:**
1. Calculates if there's a shortfall (didn't hit target size yet)
2. Distributes remaining slots to categories with highest availability
3. Keeps giving out slots until target size is reached or no category can take more

**Returns:** List of (category_idx, count) selections that hit the target size, or (None, failed_category_idx) if impossible.

**Key advantage over sequential/random:** Instead of "take minimum" or "randomly add extras", this deliberately allocates to hit a specific household size while spreading people fairly across flexible categories based on what's available.

**Basically:** "The smart way to fill households to a target size. If you want 5-person households and have flexible categories, this figures out how to distribute those 5 people proportionally based on what's available - not randomly, not greedily, but balanced. Like 'we have lots of young adults and few old adults, so let's put 3 young adults and 1 old adult in this household.'"

### _allocate_sequential

The old-school household filler

We use this in single households (0 0 0 1, 0 0 1 0)

**The gist:** The simple, straightforward way to fill households - just go through age categories one by one, grab what you need, move to the next. No fancy proportional math, just sequential processing.

#### How it works:

1. **Loop through categories in order** (kids → young adults → adults → old adults):
   - Check if we have enough people to meet the minimum
   - If not, bail out with failure
2. **For each category, decide how many to take:**
   - Exact count (like "2 adults"): Take exactly that many
   - Flexible (like ">=1 kids"):
     - If allocate_flexible=False: Take only the minimum
     - If allocate_flexible=True: Randomly pick a number between minimum and available
       - Example: Need >=2, have 10 available → randomly picks 2-10
     - Respects max_size constraint if specified
3. **Apply max_size constraint:**
   - If adding this category would exceed max household size, reduces the count
   - If reduced count is less than minimum required, fails (can't satisfy pattern)
4. **Track running total:** Keeps adding up how many people selected so far
5. **Return the plan:** List of (category_idx, count) for each category

**Key differences from balanced distribution:**
- Random allocation for flexible categories, not proportional
- No target size to hit - just processes each category independently
- Simpler logic, no remainder distribution

**Returns:** List of selections if successful, or ([], failed_category_idx) if failed.

**Basically:** "The no-frills sequential approach. Walk through categories in order, take what you need (exact or random for flexible), and move on. It's like filling out a form line by line instead of calculating the optimal distribution across all fields at once."

Think: "Just take minimums" (allocate_flexible=False) vs "randomly add extras as you go" (allocate_flexible=True).

### _select_roles_with_backtracking

The household matchmaker with a time machine

**The gist:** Tries to fill all the roles in a household (kids, adults, etc.) while respecting constraints. If it gets stuck, it goes back in time and tries different people.

#### How it works:

1. Loops through roles in order defined by the rule (e.g., kids → adults → old adults)
2. For each role, tries to find the right number of people who satisfy all constraints
   - `_adjust_role_count_for_pattern`
   - `_prepare_role_candidates`
   - `_can_skip_role_with_no_candidates`
3. Can select people as:
   - **Pairs** (for couples - finds two compatible people)
     - `_find_pair_constraint_for_role`
     - [`select_pair`](#select_pair)
   - **"Any" count** (flexible - uses minimum from pattern)
     - [`select_person_with_constraint`](#select_person_with_constraint)
   - **Exact count** (specific number needed)
     - [`select_person_with_constraint`](#select_person_with_constraint)
4. Each person selected gets validated against already-selected people (age gaps, etc.)

#### The backtracking magic:

- If a later role fails (can't find valid adults), it doesn't just give up
- Goes back to the first role and tries picking different people
- Keeps track of who it already tried to avoid infinite loops
- Will retry up to max_backtracks times
- Example: "Couldn't find adults for those kids? Let me pick different kids and try again"

#### Key features:

- Adjusts role counts based on demoted patterns (if pattern says "1 kid" but rule says "2 kids", uses the pattern's count) (`_adjust_role_count_for_pattern`)
- Can skip roles that allow zero people (`_can_skip_role_with_no_candidates`)
- Avoids duplicate attempts by tracking tried combinations
- Logs everything if you want detailed debugging

**Returns:** Dictionary mapping role names to lists of selected people, or (None, failed_category_idx) if it exhausted all options.

**Basically:** "Play matchmaker for a household, and if your first matchup doesn't work, rewind and try different combinations until something clicks (or you run out of tries)."

### select_pair

The matchmaker for couples/pairs

**The gist:** Finds two compatible people from a pool to form a pair (could be romantic partners, roommates, siblings, whatever). Makes sure they're actually compatible based on constraints.

#### How it works:

1. **Decides pair type:** Randomly picks if they should be same or different on some attribute (usually sex) depending on what the user set. Like 5% chance of same-sex couple, 95% opposite-sex.
2. **Pick person #1:** Randomly grabs someone and validates them against existing people (e.g., "is this person old enough to be a parent of those kids we already picked?") (`validate_numerical_attribute_difference_constraint`)
3. **Pick person #2:**
   - Filters candidates by the required categorical attribute (same/different sex)
   - Checks if they're compatible with person #1 (age difference not too big) (`validate_pair_numerical_attribute_difference`)
   - Also validates against existing people (both partners need to meet constraints) (`validate_numerical_attribute_difference_constraint`)
4. **Optimization tricks:**
   - Pre-shuffles candidates to avoid repeated random selections
   - Pre-groups candidates by attribute for faster filtering
   - Tries up to max_attempts combinations

**Fallback:** If it can't find a "perfect" pair, but use_best_candidate is on, it'll pick the "least bad" option (smallest constraint violations) rather than failing completely. (`calculate_pair_numerical_attribute_penalty`)

**Returns:** Either (person1, person2) if successful, or None if it couldn't find any valid pair.

**Basically:** "Find me two people who work well together based on constraints like age gaps and whether they should be same/different sex, and be smart about searching efficiently through candidates."

### select_person_with_constraint

The picky person picker

**The gist:** Pick ONE person from a pool who satisfies all constraints (like age gaps with already-selected people). Tries to be smart about it instead of just random guessing.

#### How it works:

1. **Smart prioritization (the clever bit):**
   - If there's a preferred_distribution configured (like "parents should be ~30 years older than kids"), it samples from that distribution (normal, uniform, etc.)
   - Narrows down candidates to people close to that target age (within tolerance)
   - Example: If kids are age 5, target adult age might be 35±10, so it focuses on adults aged 25-45
2. **Try random selection:**
   - Picks random people from the prioritized pool (up to max_attempts)
   - Validates each against constraints (age differences, etc.)
   - Returns first valid person found
3. **Fallback - "best bad option":**
   - If no perfect match found, calculates a "penalty score" for every candidate
   - Picks the one with lowest penalty (least constraint violations)
   - Logs a warning that it's violating constraints
4. **Give up:**
   - If use_best_candidate is disabled and nothing perfect found, returns None

**Returns:** A Person object if successful, or None if totally failed.

**Basically:** "Find me one person who fits the constraints, and be smart by targeting realistic age ranges first. If you can't find a perfect match, give me the 'least wrong' option rather than failing completely."

---

## Household Excess

It kicks off with `allocate_excess_to_households`

### allocate_excess_to_households

The "squeeze more people in" method

**The gist:** Takes leftover people and stuffs them into existing households that were created earlier. Like "we have extra young adults lying around, let's add them to family households."

#### How it works:

1. **Find target households:** Filters existing households by pattern (e.g., only households that were originally ">=2 >=0 2 0" - families with flexible young adults)
2. **Shuffle for fairness:** Randomizes household order so everyone gets an equal shot at extra people
3. **Figure out how many to add:**
   - If you give it an add_distribution, it samples from that (like "60% get 1 person, 30% get 2, 10% get none")
   - Otherwise, fills each household to the max allowed
4. **Add people one by one:**
   - For each household, grabs people from the pool of the specified category
   - Checks constraints before adding (like "max 4 kids+young adults total") (`_check_constraints_if_added`)
   - If using a relationship rule, validates the person against existing household members (age gaps, etc.) ([`_select_person_for_excess_with_rule`](#_select_person_for_excess_with_rule))
   - If no rule, just grabs first available person
   - Stops when: out of people, hit the target count, or constraints would be violated
5. **Track everything:** Counts how many people added, how many households modified

#### Key features:

- **target_patterns**: Only add to specific household types
- **add_category**: Which age group to add (e.g., "Young Adults", "Kids")
- **constraints**: Rules like "max 4 kids+young adults combined"
- **add_distribution**: Probability distribution for how many to add per household
- **rule_name**: Apply relationship rules so added people make sense (ages match, etc.)

**Returns:** Stats dict with people added, households modified, etc.

**Basically:** "Got leftover people after main allocation? This squeezes them into existing households that have room, respecting constraints and optionally checking if they'd make sense relationship-wise (like not adding a 5-year-old 'sibling' to 20-year-old adults)."

### _select_person_for_excess_with_rule

The "does this person fit in?" checker

**The gist:** When you're adding someone to an existing household, this makes sure they actually make sense with the people already living there (age-wise, relationship-wise, etc.).

#### How it works:

1. **Map existing residents to roles:**
   - Looks at everyone already in the household
   - Figures out which role they fill based on the relationship rule (kids, adults, old adults, etc.)
   - Creates a dictionary like {"kids": [person1, person2], "adults": [person3, person4]}
2. **Figure out the new person's role:**
   - Looks at what category you're trying to add (e.g., "Young Adults")
   - Finds which role in the rule that category belongs to
   - If the category isn't in any role, just grabs first available person (no validation)
3. **Find a compatible person:**
   - Calls [`select_person_with_constraint`](#select_person_with_constraint) (the smart picker we talked about earlier)
   - Passes in the existing household members so constraints can be checked
   - Example: "Is this 25-year-old young adult at least 18 years younger than those adults already in the house?"

**Returns:** A valid Person who won't break the household's relationship logic, or None if nobody fits.

**Basically:** "When adding someone to an existing household, make sure they're a realistic fit - like not adding a 10-year-old 'sibling' when the 'adults' are only 22, or making sure new adults are old enough to be parents of existing kids."

It's the gatekeeper that prevents weird household compositions when you're squeezing in leftover people.

---

## Household Promotion

It kicks off with `execute_household_promotion_step` which asks 'are there promotion rules stated in the yaml?'

If yes it calls [`promote_with_rules`](#promote_with_rules), if no, it calls [`promote_and_allocate`](#promote_and_allocate)

### promote_with_rules

The household upgrader with fine control

**The gist:** Takes households that were created with fixed patterns (like "0 0 2 0" - exactly 2 adults) and "promotes" them to flexible patterns (like "0 >=0 2 0" - 2 adults plus any number of young adults), then fills them with leftover people.

#### How it works:

1. **Process each promotion rule:**
   - Each rule says: "Find households with pattern X, upgrade them to pattern Y, and you can add categories A, B, C (up to N people)"
   - Example: "Find '0 0 2 0' households → promote to '0 >=0 2 0' → add Young Adults (max 3 per household)"
2. **Find matching households:**
   - Loops through all existing households
   - Finds ones with the source_pattern (e.g., "0 0 2 0")
3. **Add people by category:**
   - For each accepted category (like "Young Adults", "Kids"):
     - Checks how many are currently in the household
     - Figures out how many more can be added based on:
       - Target pattern's max (if specified)
       - Rule's max_to_add limit
       - How many are actually available
     - Grabs people and adds them to the household
4. **"Promote" the household:**
   - First person added triggers the promotion
   - Updates household's actual_pattern property to the new flexible pattern
   - Logs it as "promoted"
5. **Track everything:** Counts how many households promoted, people added, etc.

#### Key differences from [`allocate_excess_to_households`](#allocate_excess_to_households):

- This one changes the household pattern (promotes from exact to flexible)
- Uses a list of explicit rules instead of one pattern + distribution
- Each rule can target different categories and have different limits

**Returns:** Stats dict with households promoted, people added, etc.

**Basically:** "Take households with exact compositions and upgrade them to allow flexibility, then fill them with leftover people according to specific rules about which categories are acceptable and how many to add. It's like saying 'those couple households? Let's allow them to have kids now' and then adding available kids to them."

### promote_and_allocate

The greedy cleanup method

**The gist:** Got leftover people and need to put them somewhere? This method automatically promotes existing households to make room, then greedily stuffs ALL remaining people into them. No rules, no distribution - just "find room and fill 'er up."

#### How it works:

1. **Process each target category:**
   - You tell it which categories to allocate (e.g., "Young Adults", "Kids")
   - Loops through each one
2. **Find geo units with leftover people:**
   - For each geo unit that has people in this category still unallocated
   - Grabs all the households in that geo unit
   - Shuffles them for fairness
3. **Try to fit people into each household:**
   - Checks if the household can currently accept someone from this category
   - If not, automatically promotes the household pattern to make room
   - Promotion follows priority order (from config)
   - Tries up to max_attempts promotions
   - Example: "0 0 2 0" → "0 >=0 2 0" → ">=0 >=0 2 0"
4. **Add ALL available people:**
   - Once a household can accept this category, adds as many as possible
   - For flexible categories (>=), adds EVERYONE available (greedy!)
   - For fixed categories, adds up to the max
   - Keeps going until pool is empty
5. **Track promotions:** Marks households as promoted and logs the pattern changes

#### Key differences from [`promote_with_rules`](#promote_with_rules):

- This one is automatic - you don't specify which patterns to promote, it figures it out
- It's greedy - tries to allocate ALL remaining people in target categories
- Uses priority order from config instead of explicit rules
- Promotes households on-the-fly as needed

**Returns:** Stats dict with households promoted, people added, etc.

**Basically:** "The 'throw everyone somewhere' method. Takes leftover people, automatically expands existing households to fit them, and stuffs everyone in. Great for cleanup rounds when you just need to allocate remaining people without worrying about distributions or specific rules."

---

## Household Overflow

This is kicked off with `_execute_household_overflow_step` and it simply just runs `allocate_overflow_to_households`

### allocate_overflow_to_households

The nuclear option for leftovers

**The gist:** The "desperation round" - takes ALL remaining people of one category and distributes them across existing households without caring about max size constraints. Just gets everyone housed, even if households get unrealistically big.

#### How it works:

1. **Group households:**
   - Filters to target patterns
   - Groups them by (geo_unit, pattern) combo
   - Each geo unit gets its own pool of people
2. **Calculate proportional distribution with bias:**
   - For each geo unit, figures out how to split up the available people
   - If you give it pattern_bias (like {"0 >=0 0 0": 2.0, "2 >=0 2 0": 1.0}), certain patterns get more people
   - Example: Single households get 2x allocation compared to family households
   - Proportions based on: (pattern_weight × num_households_with_pattern)
3. **Allocate proportionally to patterns:**
   - Calculates how many people each pattern group should get
   - Distributes any remainder to highest-weighted patterns
4. **Distribute balancedly within each pattern:**
   - For households of the same pattern, spreads people evenly
   - Uses "base + remainder" distribution (some get N, some get N+1)
   - Shuffles households for fairness
5. **Add people sequentially:**
   - Loops through households, adding the calculated number to each
   - Ignores any size constraints - just adds them
   - Removes allocated people from pool

#### Key features:

- **Balanced distribution**: Spreads people evenly, not random or greedy
- **Pattern bias**: Can favor certain household types over others
- **No constraints**: WARNING - ignores max household size
- **Geo-unit aware**: Only allocates people within their own geo unit

**Returns:** Stats dict with people added, households modified, etc.

**Basically:** "The last resort method when you've got leftover people and just need to put them SOMEWHERE. Distributes them fairly across existing households with optional bias towards certain patterns, completely ignoring any size limits. Use when realism < getting everyone housed."
