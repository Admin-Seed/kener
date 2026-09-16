#!/usr/bin/env node
/**
 * Generate the monitor avatars: a white brand mark on a flat coloured disc.
 *
 * Two-axis system — the GLYPH says which product, the COLOUR says which
 * environment. Colour is never the only signal; the row label already names the
 * environment, so this is redundant encoding rather than colour-as-meaning.
 *
 * Run inside the Kener container, which already ships `sharp`:
 *
 *   docker cp tools/make-avatars.js kener-kener-1:/tmp/
 *   docker cp brand/. kener-kener-1:/tmp/brand/
 *   docker exec kener-kener-1 node /tmp/make-avatars.js /tmp/brand /tmp/out
 *
 * Design notes, so the numbers are not mystery constants:
 *
 *   SIZE 160      4x the 40px render, so it stays crisp on high-DPI screens
 *                 while each file stays a couple of kB.
 *   GLYPH 0.54    Kener clips the avatar to a circle (`rounded-full` +
 *                 `overflow-hidden`). A square inscribed in a circle can only
 *                 reach ~0.707 of the diameter; 0.54 leaves the mark breathing
 *                 room inside the clip instead of crowding the edge.
 *   .trim()       The two source marks carry different amounts of transparent
 *                 margin. Trimming to ink first makes them the same OPTICAL
 *                 size rather than the same file size.
 *   flat fill     No gradient, no shadow. At 40px a gradient turns to mud and a
 *                 shadow reads as a smudge.
 */
const sharp = require("sharp");
const path = require("path");
const fs = require("fs");

const SRC = process.argv[2] || "/tmp/brand";
const OUT = process.argv[3] || "/tmp/out";
const SIZE = 160;
const GLYPH = Math.round(SIZE * 0.54);

const SEED = "logo-white.png";
const COORTEX = "logo-coortex-white.png";

// Fills are drawn from the board's own palette family; #0B5ECB is already
// ACCENT_FOREGROUND in the light theme. Contrast against the white glyph was
// measured, not estimated: 6.0, 7.1, 5.5, 7.6 and 10.4 to 1, all clear of
// WCAG AA at 4.5.
const AVATARS = [
  ["seed-production.png", SEED, "#0B5ECB"], // brand blue  - production
  ["seed-staging.png", SEED, "#6D28D9"], // violet      - homologação
  ["seed-api.png", SEED, "#0F766E"], // teal        - integration API
  ["seed-infra.png", SEED, "#334155"], // graphite    - gateway, certs, internal
  ["coortex-production.png", COORTEX, "#0B5ECB"],
  ["coortex-development.png", COORTEX, "#475569"], // slate - lower environment
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  for (const [name, src, fill] of AVATARS) {
    const glyph = await sharp(path.join(SRC, src))
      .trim() // to ink bounds, so both marks match optically
      .resize({ width: GLYPH, height: GLYPH, fit: "inside" })
      .toBuffer();

    const out = path.join(OUT, name);
    await sharp({
      create: { width: SIZE, height: SIZE, channels: 4, background: fill },
    })
      .composite([{ input: glyph, gravity: "center" }])
      .png({ compressionLevel: 9 })
      .toFile(out);

    const { width, height } = await sharp(out).metadata();
    console.log(
      `${name.padEnd(26)} ${fill}  ${width}x${height}  ${fs.statSync(out).size} bytes`
    );
  }
})().catch((e) => {
  console.error("FAILED:", e.message);
  process.exit(1);
});
