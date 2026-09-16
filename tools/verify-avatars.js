// Prove each avatar is a white mark on a coloured disc, not a blank disc.
// Checks: the corner is the intended fill, and a plausible share of pixels are
// near-white (the glyph). A file existing proves nothing.
const sharp = require("sharp");
const fs = require("fs");
const path = require("path");

const DIR = process.argv[2] || "/tmp/out";
const EXPECT = {
  "seed-production.png": [11, 94, 203],
  "seed-staging.png": [109, 40, 217],
  "seed-api.png": [15, 118, 110],
  "seed-infra.png": [51, 65, 85],
  "coortex-production.png": [11, 94, 203],
  "coortex-development.png": [71, 85, 105],
};

(async () => {
  let bad = 0;
  for (const name of Object.keys(EXPECT)) {
    const p = path.join(DIR, name);
    const { data, info } = await sharp(p).raw().toBuffer({ resolveWithObject: true });
    const ch = info.channels;

    const corner = [data[0], data[1], data[2]];
    const [er, eg, eb] = EXPECT[name];
    const fillOk =
      Math.abs(corner[0] - er) < 3 && Math.abs(corner[1] - eg) < 3 && Math.abs(corner[2] - eb) < 3;

    let white = 0;
    const total = info.width * info.height;
    for (let i = 0; i < total; i++) {
      const o = i * ch;
      if (data[o] > 225 && data[o + 1] > 225 && data[o + 2] > 225) white++;
    }
    const pct = (100 * white) / total;
    // A trimmed mark scaled to 54% of the canvas covers a modest share of it.
    const glyphOk = pct > 3 && pct < 35;

    if (!fillOk || !glyphOk) bad++;
    console.log(
      `${name.padEnd(26)} fill ${fillOk ? "ok " : "BAD"} rgb(${corner})  ` +
        `glyph ${glyphOk ? "ok " : "BAD"} ${pct.toFixed(1)}% white`
    );
  }
  if (bad) {
    console.error(`\n${bad} avatar(s) failed`);
    process.exit(1);
  }
  console.log("\nall six verified");
})();
