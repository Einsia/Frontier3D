# Scene and gameplay requirements

Use the reference image to determine the extent, composition and proportions of the open-world environment. The village is the detailed, traversable gameplay focus within that environment; its building count does not define the extent of the surrounding landscape. Use one block = 100 Unreal centimetres, Z up. Include 11 distinct buildings (eight houses, two smithies and one storehouse), at least eight furnished accessible interiors, a village square, connected paths, two irrigated crop plots, a livestock pen, vegetation and at least 40 purposeful props. Use the reference for the composition and character of the environment; infer unseen details consistently. Water simulation, animal AI, combat and a complete survival system are not required.

The player uses an ACharacter with gravity, walking collision, radius 30 cm and half-height 85 cm, eye height about 160 cm, WASD movement, mouse look and E to use. Interaction uses a 300 cm occluded eye ray. Use the same gameplay path for manual and automated interaction.

## Gameplay

1. Four required hinged doors: `house01.door`, `house02.door`, `smithy01.door`, `storehouse.door`. Each has a pivoted visible leaf and collision. Opening takes 0.4–1.0 seconds, rotates approximately 90 degrees, permits actual passage, and closing restores the barrier. The door's swept motion must clear its wall, furnishings and neighboring geometry. Other building entrances may be permanently open. The same interaction path must be used by manual E input and automation.
2. Two chests: `house01.chest` and `storehouse.chest`. A visible hinged lid opens/closes; contents can be taken once and persist during travel. Start with one seed bundle in the house chest and one tool bundle in the storehouse chest; do not duplicate it on repeat interaction. Actions `use` (lid), `take` (contents). Clearly show the state to the player.
3. One livestock gate: `pen.gate`, hinged and collidable. Closed blocks passage, open permits passage. Repeated use restores the original state.
4. Six crop plants `farm.crop01` … `farm.crop06`. `harvest` changes a mature visible plant to a harvested plot once and grants one crop. `plant` consumes a seed and restores visible immature planting. Repeated harvest of a harvested/immature plant grants nothing. There is no growth timing test.
5. Three editable blocks `edit.block01` … `edit.block03` in a clearly marked 3×1 patch near the storehouse. `remove` removes visible geometry AND its collision; `place` restores both. Other terrain cannot be edited. Use no global-world rebuild to hide incorrect state.
6. A furnace `smithy01.furnace`: `process` consumes one carried crop, visibly lights the furnace for at least one second, and then grants one processed item. Processing without input must do nothing. Do not simulate success solely with a text overlay or a JSON flag.
7. State must survive walking between the house, farm, smithy and storehouse in the same session. Do not reset on distance, visibility or time. Saving across process restart is optional.

Use an eye-ray interaction distance of 300 cm with occlusion. An action aimed through a wall or from a distant position must not activate its target. Enforce preconditions in gameplay, not only in the automation caller. Do not special-case benchmark filenames or plans.

