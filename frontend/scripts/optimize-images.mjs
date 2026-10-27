// Builds the raster assets from SVG sources: favicon set and the Open Graph image (PNG and WebP).
// Run with `npm run images`. No third party photographs are used, so there is nothing to attribute.
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const pub = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public");

const favicon = await readFile(path.join(pub, "favicon.svg"));
await sharp(favicon, { density: 384 }).resize(32, 32).png().toFile(path.join(pub, "favicon-32.png"));
await sharp(favicon, { density: 1152 }).resize(180, 180).png().toFile(path.join(pub, "apple-touch-icon.png"));

const og = await readFile(path.join(pub, "og-source.svg"));
await sharp(og).resize(1200, 630).png({ compressionLevel: 9 }).toFile(path.join(pub, "og-image.png"));
await sharp(og).resize(1200, 630).webp({ quality: 85 }).toFile(path.join(pub, "og-image.webp"));
await writeFile(path.join(pub, "images", ".keep"), "").catch(() => undefined);
console.log("images written");
