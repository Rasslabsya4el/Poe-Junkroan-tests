Target product flow for the reboot MVP:

1. Input
- User chooses a skill as the starting point.

2. Skill passport
- Scripts extract what the skill fundamentally is: attack or spell, hit or DoT surfaces, delivery compatibility, geometry hooks, and known mechanic packages.

3. Scaling prediction
- Rules map the skill passport to promising scaling vectors and route families.
- The system should narrow the search space before touching full build authoring.

4. Wearable affix layer
- A canonical catalog of wearable item affixes provides the gear-side source of stats, tiers, and realism signals.

5. Build assembly
- Tree packages, supports, items, and config are composed under rails and evaluated in PoB.

6. Evaluator
- The evaluator compares concrete PoB states, not abstract prose.
- It should decide whether a change improved the build and why.

Architectural principle:
- The LLM chooses and sequences tools.
- The scripts own the formulas, the tables, and the data transformations.

Immediate spec pressure:
- The wearable affix catalog must be trustworthy before new gear-generation logic can be designed with confidence.
