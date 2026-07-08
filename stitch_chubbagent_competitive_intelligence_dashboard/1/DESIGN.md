---
name: ChubbAgent Enterprise
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#43474e'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#73777f'
  outline-variant: '#c3c6d0'
  surface-tint: '#3e608b'
  primary: '#002446'
  on-primary: '#ffffff'
  primary-container: '#123a63'
  on-primary-container: '#83a5d4'
  inverse-primary: '#a6c9fa'
  secondary: '#30628a'
  on-secondary: '#ffffff'
  secondary-container: '#a1d1fe'
  on-secondary-container: '#265a81'
  tertiary: '#2e2100'
  on-tertiary: '#ffffff'
  tertiary-container: '#483600'
  on-tertiary-container: '#c89c15'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d3e4ff'
  primary-fixed-dim: '#a6c9fa'
  on-primary-fixed: '#001c38'
  on-primary-fixed-variant: '#244872'
  secondary-fixed: '#cde5ff'
  secondary-fixed-dim: '#9ccbf8'
  on-secondary-fixed: '#001d32'
  on-secondary-fixed-variant: '#104a71'
  tertiary-fixed: '#ffdf95'
  tertiary-fixed-dim: '#f0c03e'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#594400'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  display-lg:
    fontFamily: IBM Plex Sans
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: IBM Plex Sans
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  headline-md:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: IBM Plex Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
  headline-lg-mobile:
    fontFamily: IBM Plex Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 20px
  margin-page: 40px
---

## Brand & Style

The design system for this dashboard is rooted in Scandinavian functionalism—prioritizing clarity, utility, and a sense of calm reliability. As an enterprise-grade tool for secure storage management, the UI must evoke absolute trust and professional precision.

The aesthetic follows a **Modern Corporate** direction with **Minimalist** influences. It avoids unnecessary decoration, instead using generous whitespace, structured data grids, and a refined "Steel and Navy" palette to communicate security. The experience should feel like a high-performance instrument: quiet, responsive, and authoritative.

Key principles:
- **Functional Transparency:** Information hierarchy is immediate; critical security statuses are never obscured.
- **Pragmatic Elegance:** High-density data is managed through subtle tonal shifts rather than heavy borders.
- **Precision:** Alignment and spacing are rigorous, reflecting the mechanical precision of the physical safes being monitored.

## Colors

The palette is anchored by **Deep Navy (#123A63)**, providing a foundation of institutional stability. **Steel Blue** and **Soft Blue** are used for secondary interaction states and subtle background layering. 

**Swedish Yellow (#F5C542)** is reserved exclusively for high-impact visual cues: KPIs, active warning states, or primary call-to-actions that require immediate attention within a dense data environment. 

The neutral scale favors a cool-gray spectrum to maintain the professional Scandinavian "Steel" feel, using **White** for primary surfaces and **Light Gray (#F6F7F8)** for application backgrounds and grouping containers.

## Typography

This design system utilizes a dual-font approach to balance systematic efficiency with corporate authority. **IBM Plex Sans** is used for headings and UI labels to provide a technical, structured feel reminiscent of industrial engineering. **Inter** is used for all body text and data entries, selected for its exceptional legibility in high-density tables and dashboards.

Numerical data should utilize the tabular lining figures available in both fonts to ensure columns of numbers align perfectly for easy comparison. Use `label-md` for table headers and section overviews to create clear visual separation from the data itself.

## Layout & Spacing

The layout follows a **Fluid Grid** system within a max-width container of 1600px for desktop. For data-heavy views, a 12-column grid is used with 20px gutters. 

Spacing follows a strict 4px/8px baseline rhythm to ensure mathematical harmony. In the "ChubbAgent" dashboard, vertical density is key; therefore, table rows and list items should utilize "Compact" (32px) or "Standard" (44px) heights depending on the data complexity.

**Breakpoints:**
- **Desktop (1280px+):** Full sidebar navigation, 12-column grid, 40px page margins.
- **Tablet (768px - 1279px):** Collapsed sidebar (icons only), 8-column grid, 24px page margins.
- **Mobile (<767px):** Bottom bar or hamburger menu, single column fluid, 16px page margins.

## Elevation & Depth

To maintain a clean, professional aesthetic, depth is communicated through **Tonal Layering** supplemented by **Ambient Shadows**.

- **Level 0 (Background):** #F6F7F8. Used for the main application canvas.
- **Level 1 (Cards/Surface):** #FFFFFF. Used for the primary content containers. Features a very soft, diffused shadow (0px 2px 8px rgba(18, 58, 99, 0.05)).
- **Level 2 (Popovers/Modals):** #FFFFFF. Features a more pronounced shadow (0px 8px 24px rgba(18, 58, 99, 0.12)) to indicate temporary interaction layers.

Avoid heavy borders; instead, use 1px strokes in **Medium Gray (#D6D9DD)** only when necessary to separate distinct functional areas within a single white surface.

## Shapes

The shape language is "Approachable Technical." We use a consistent **10px corner radius** (defined as `rounded-lg` in this system) for primary UI components like cards, buttons, and input fields. 

- **Small elements (Checkboxes, Tags):** 4px radius.
- **Standard containers (Cards, Modals):** 10px radius.
- **Search bars:** Fully pill-shaped (rounded-full) to distinguish them from data entry fields.

This radius strikes a balance between the hard angles of industrial hardware and the softness of modern enterprise software.

## Components

### Buttons
- **Primary:** Deep Navy (#123A63) background, white text. 10px radius. High contrast.
- **Secondary:** White background, 1px Steel Blue stroke, Deep Navy text.
- **Ghost:** No background/stroke. Steel Blue text. Used for secondary actions in tables.

### Tables & Data Grids
- **Header:** Light Gray (#F6F7F8) background, IBM Plex Sans Bold (12px).
- **Rows:** 44px minimum height. Subtle #D6D9DD bottom border. Hover state uses #DCEAF5 (Soft Blue).
- **Cells:** Inter (14px). Use tabular numbers for metrics.

### Input Fields
- **Default:** White background, 1px #D6D9DD stroke. 10px radius.
- **Focus:** 1px #123A63 stroke with a soft 3px #DCEAF5 outer glow.
- **Label:** IBM Plex Sans (12px, Medium) positioned above the field.

### Status Chips
- **Success:** Soft Green background with Dark Green text.
- **Alert:** Soft Red background with Dark Red text. 
- All chips use a 4px radius and are semi-bold.

### Timeline Feeds
- Vertical 2px line in Medium Gray.
- Milestones marked with 8px circular dots.
- Security-critical events use the Swedish Yellow (#F5C542) for the milestone dot.

### Charts
- Use a palette of Steel Blue, Deep Navy, and Soft Blue. 
- Highlight or "Current Value" lines should use Swedish Yellow for immediate visibility. 
- No grid lines on X/Y axes unless absolutely necessary for reading precise values.