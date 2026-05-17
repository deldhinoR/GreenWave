# Design System Specification: The Kinetic Flow

## 1. Overview & Creative North Star: "The Living Grid"
This design system moves away from the rigid, static nature of traditional data dashboards. Our Creative North Star is **"The Living Grid."** We treat traffic data not as stagnant numbers, but as a fluid, organic pulse moving through a city. 

To achieve a "High-End Editorial" feel for a technical tool, we reject the "template" look. We utilize intentional white space, layered depth, and a sophisticated interplay between the technical (Slate Gray) and the organic (Deep Emerald). The aesthetic is one of **"Technical Zen"**—where high-velocity data meets high-efficiency ecology.

---

### 2. Colors: Tonal Depth over Structural Lines
We define the environment through light and color, not through boxes and borders.

**The "No-Line" Rule:** 
Explicitly prohibit 1px solid borders for sectioning. Boundaries must be defined solely through background color shifts or subtle tonal transitions. For example, a `surface-container-low` section sitting on a `surface` background provides all the definition a professional eye needs.

**Surface Hierarchy & Nesting:**
UI is a series of physical layers—like stacked sheets of frosted glass.
- **Base Layer:** `surface` (#f7fbf0)
- **Secondary Workspaces:** `surface-container-low` (#f1f5eb)
- **Primary Content Cards:** `surface-container-lowest` (#ffffff)
- **Elevated Intersections:** `surface-container-high` (#e5eadf)

**The "Glass & Gradient" Rule:** 
To represent the "Green Wave" concept, use subtle linear gradients for primary actions and hero data points:
- **Primary Gradient:** From `primary` (#0d631b) to `primary-container` (#2e7d32) at a 135° angle.
- **Glassmorphism:** For floating map overlays or tooltips, use `surface-container-lowest` at 85% opacity with a `24px` backdrop-blur.

---

### 3. Typography: The Editorial Authority
We pair the technical precision of **Inter** with the architectural character of **Manrope** to create a hierarchy that feels both human and engineered.

- **Display & Headlines (Manrope):** Used for high-level metrics and page titles. The wide apertures of Manrope convey openness and modernity.
- **Body & Labels (Inter):** Used for dense data, table rows, and system feedback. Inter’s tall x-height ensures legibility in high-pressure monitoring environments.

**Key Scales:**
- **Display-LG (3.5rem):** For hero traffic flow percentages.
- **Headline-SM (1.5rem):** For card titles and section headers.
- **Label-MD (0.75rem, All Caps, 5% Letter Spacing):** For technical metadata and "Traffic Light" statuses.

---

### 4. Elevation & Depth: Tonal Layering
We do not use shadows to make things "pop"; we use them to indicate "reach."

- **The Layering Principle:** Place a `surface-container-lowest` card on a `surface-container-low` background. This creates a soft, natural lift that mimics fine stationery.
- **Ambient Shadows:** When an element must float (e.g., a map control), use an extra-diffused shadow: `offset: 0 8px, blur: 24px, color: rgba(24, 29, 23, 0.06)`. Note the use of a tinted shadow (using the `on-surface` hue) rather than neutral black.
- **The "Ghost Border" Fallback:** If a border is required for accessibility (e.g., in high-contrast mode), use the `outline-variant` (#bfcaba) at **15% opacity**. Never use a 100% opaque border.

---

### 5. Components: Precision Primitives

#### **Buttons**
- **Primary:** Gradient fill (Deep Emerald to Emerald Container), `0.375rem (md)` corner radius. No border. White text.
- **Secondary:** `surface-container-highest` background with `on-surface` text.
- **Tertiary:** No background. `primary` text with a subtle `8px` hover state using `primary-container` at 10% opacity.

#### **Input Fields**
- Forgo the four-sided box. Use a `surface-container-low` background with a `2px` bottom-stroke in `outline` (#707a6c) that transitions to `primary` (#0d631b) on focus.

#### **Status "Pulse" Chips**
- Instead of standard solid chips, use a transparent background with a "Ghost Border" and a 6px "Living Pulse" dot. 
- **Green Wave Active:** Dot color `primary`, with a soft glow effect.

#### **Cards & Lists**
- **No Dividers:** Forbid the use of 1px lines between list items. Use an `8px` vertical gap.
- **The "Map-First" Card:** Map-based cards should use `surface-container-lowest` with an `xl (0.75rem)` corner radius to soften the technical edge.

---

### 6. Do's and Don'ts

**Do:**
- **Do** use `primary-fixed-dim` (#88d982) for secondary data visualizations to ensure the "Green" theme remains sophisticated, not overwhelming.
- **Do** utilize `surface-bright` for hover states on white cards to create a "shimmer" effect.
- **Do** use `tertiary` (#923357) sparingly for critical alerts; its plum/pink tone provides a professional alternative to standard "emergency red."

**Don't:**
- **Don't** use pure black (#000000) for text. Always use `on-surface` (#181d17) to maintain the organic, eco-friendly feel.
- **Don't** use standard "Drop Shadows" from software defaults. They feel "dirty" against our clean Emerald palette.
- **Don't** use hard corners. Traffic flows; the UI should too. Always use at least the `md (0.375rem)` radius.

---

### 7. Signature Interaction: The Flow State
When the system updates traffic data, elements should not "snap." Use a **300ms "Cubic-Bezier (0.4, 0, 0.2, 1)"** transition for background color shifts and card expansions. This mimics the acceleration and deceleration of natural traffic, reinforcing the "Greenwave" brand identity at a kinetic level.