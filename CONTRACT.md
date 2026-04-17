# MTGLib Card Contract

## Canonical Identity Rule

One Markdown file represents one canonical gameplay identity. Reprints, alternate art, promos, set codes, and collector variants do not create separate files. Multi-face cards, split cards, transform cards, and adventure cards remain one canonical file that includes all gameplay-relevant faces or halves.

## Filename And Slug Policy

- Use lowercase ASCII only.
- Use hyphens as separators.
- Use the canonical card name as the slug base.
- Remove punctuation that is not needed for word separation.
- For multi-part cards, join all canonical face or half names in printed order with hyphens.
- The filename must be `<slug>.md`.
- The `## Slug` section value must exactly match the filename without `.md`.

Examples:

- `llanowar-elves.md`
- `wear-tear.md`
- `bonecrusher-giant-stomp.md`
- `fable-of-the-mirror-breaker-reflection-of-kiki-jiki.md`

## Exact Card Section Order

Every card file must start with these sections in this order:

1. `# <display name>`
2. `## Canonical Name`
3. `## Slug`
4. `## Layout`
5. `## Sets`

Single-face cards then continue in this order:

6. `## Mana Cost`
7. `## Type Line`
8. `## Keywords`
9. `## Rules Text`
10. `## Stats` when required
11. `## Loyalty` when required

Multi-face cards replace the single-face body sections with this structure:

6. `## Faces`
7. For each face, half, or side in printed order:
   - `### Face <n>`
   - `#### Name`
   - `#### Mana Cost`
   - `#### Type Line`
   - `#### Keywords`
   - `#### Rules Text`
   - `#### Stats` when required
   - `#### Loyalty` when required

No frontmatter is allowed.

## Sets Section Policy

- `## Sets` must be a Markdown list.
- Each entry must be a human-readable set name such as `- Wilds of Eldraine`.
- Keep the list sorted alphabetically for deterministic output.
- The section represents the set names currently associated with that canonical card in this corpus.
- If a card file is updated because another set should be added to the same canonical card, append that set to the list without changing unrelated card content.

## Conditional Sections

- `Stats` is required for creatures and any other card face that has printed power and toughness.
- `Loyalty` is required for planeswalkers and planeswalker faces.
- Multi-face cards must use the `Faces` structure and must not improvise with free-form prose.
- If a section has no meaningful entries, keep the section and use `- None` where a list is expected.

## Mana-Cost Normalization Approach

Mana cost must remain human-readable and regular enough for parsing.

For a single-face card, `## Mana Cost` uses this field order:

- `Printed:` ASCII rendering of the mana cost in symbol order, or `none`
- `Generic:` integer count
- `White:` integer count
- `Blue:` integer count
- `Black:` integer count
- `Red:` integer count
- `Green:` integer count
- `Colorless:` integer count
- `Hybrid:` `none` or comma-separated symbol counts such as `G/W: 2`
- `Phyrexian:` `none` or comma-separated symbol counts such as `U/P: 1`
- `Variable:` `none` or comma-separated variables such as `X: 2`
- `Snow:` integer count

Each face in a multi-face card uses the same field order under `#### Mana Cost`.

Recommended `Printed:` examples:

- `2WW`
- `1(G/W)(G/W)`
- `U/P`
- `XX`
- `none`

Use ASCII-friendly notation only. Do not use braces or mana glyphs.

## Reminder-Text And Source Policy

- Rules text should preserve canonical Oracle-style gameplay meaning while normalizing symbol rendering to MTGLib's declared ASCII form.
- MTGLib rules-text symbol normalization uses ASCII-only symbol text in place of Oracle glyphs or brace notation.
- Use `Tap` for the tap symbol and `Untap` for the untap symbol.
- Render mana symbols as unbraced ASCII tokens such as `W`, `U`, `B`, `R`, `G`, `C`, numbers, `X`, hybrid forms like `G/W`, and phyrexian forms like `U/P`.
- Render activated or loyalty costs as a comma-separated ASCII cost list followed by a colon, such as `Tap: Add G.`, `Tap: Add CC.`, `1, Tap: ...`, `4: ...`, or `+1: ...`.
- Do not use mana braces or symbol glyphs in rules text.
- Keep reminder text only when the canonical gameplay text includes it and omitting it would drop part of the current rules wording.
- Do not add custom explanatory prose.
- Keep flavor text out of card files.
- When adding or revising entries, use one authoritative rules-text source consistently for that edit.

## Out-Of-Scope Metadata Policy

Do not include:

- legality
- prices
- set codes
- collector numbers
- rarity
- artist credits
- release dates
- printing-by-printing variations
- deck commentary

Optional commentary sections are out of scope for Phase 1. Card files should contain gameplay-relevant identity and rules information only.