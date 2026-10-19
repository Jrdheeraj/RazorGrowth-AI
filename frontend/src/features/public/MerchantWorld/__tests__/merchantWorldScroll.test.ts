// @ts-ignore
import assert from "assert";
import { computeLayerAlphas } from "../useMerchantWorldScroll.js";

console.log("Running Gemini Day-to-Night scroll unit tests...");

// 1. Initial Morning state at progress = 0
{
  const alphas = computeLayerAlphas(0);
  assert.strictEqual(alphas.morning, 1, "Morning should be 1.0 at progress 0");
  assert.strictEqual(alphas.midday, 0, "Midday should be 0.0 at progress 0");
  assert.strictEqual(alphas.sunset, 0, "Sunset should be 0.0 at progress 0");
  assert.strictEqual(alphas.night, 0, "Night should be 0.0 at progress 0");
  console.log("✓ Initial morning scene at progress 0 passed");
}

// 2. Transition toward Midday around 15% (pos = 0.45)
{
  const alphas = computeLayerAlphas(0.15);
  assert.strictEqual(alphas.morning, 1);
  assert(alphas.midday > 0.2 && alphas.midday < 0.7, "Midday should be smoothly crossfading in");
  assert.strictEqual(alphas.sunset, 0);
  assert.strictEqual(alphas.night, 0);
  console.log("✓ Transition toward midday at progress 0.15 passed");
}

// 3. Bright Midday fully active around 33%
{
  const alphas = computeLayerAlphas(0.33);
  assert.strictEqual(alphas.morning, 1);
  assert.strictEqual(alphas.midday, 1, "Midday should be 1.0 around progress 0.33");
  assert.strictEqual(alphas.sunset, 0, "Sunset should be 0.0 at progress 0.33");
  assert.strictEqual(alphas.night, 0, "Night should be 0.0 at progress 0.33");
  console.log("✓ Midday scene at progress 0.33 passed");
}

// 4. Transition toward Sunset around 50% (pos = 1.50)
{
  const alphas = computeLayerAlphas(0.50);
  assert.strictEqual(alphas.morning, 1);
  assert.strictEqual(alphas.midday, 1);
  assert(alphas.sunset > 0.2 && alphas.sunset < 0.8, "Sunset should be crossfading in around progress 0.50");
  assert.strictEqual(alphas.night, 0);
  console.log("✓ Transition toward sunset at progress 0.50 passed");
}

// 5. Sunset fully active around 66%
{
  const alphas = computeLayerAlphas(0.66);
  assert.strictEqual(alphas.morning, 1);
  assert.strictEqual(alphas.midday, 1);
  assert.strictEqual(alphas.sunset, 1, "Sunset should be 1.0 around progress 0.66");
  assert.strictEqual(alphas.night, 0, "Night should be 0.0 at progress 0.66");
  console.log("✓ Sunset scene at progress 0.66 passed");
}

// 6. Transition toward Night around 82% (pos = 2.46)
{
  const alphas = computeLayerAlphas(0.82);
  assert.strictEqual(alphas.morning, 1);
  assert.strictEqual(alphas.midday, 1);
  assert.strictEqual(alphas.sunset, 1);
  assert(alphas.night > 0.2 && alphas.night < 0.8, "Night should be crossfading in around progress 0.82");
  console.log("✓ Transition toward night at progress 0.82 passed");
}

// 7. Night fully active at 100%
{
  const alphas = computeLayerAlphas(1.0);
  assert.strictEqual(alphas.morning, 1);
  assert.strictEqual(alphas.midday, 1);
  assert.strictEqual(alphas.sunset, 1);
  assert.strictEqual(alphas.night, 1, "Night should be 1.0 at progress 1.0");
  console.log("✓ Final night scene at progress 1.0 passed");
}

// 8. Monotonic continuity test across 100 scroll steps
{
  let prevMidday = 0;
  let prevSunset = 0;
  let prevNight = 0;
  for (let i = 0; i <= 100; i++) {
    const p = i / 100;
    const a = computeLayerAlphas(p);
    assert(a.morning >= 0 && a.morning <= 1);
    assert(a.midday >= 0 && a.midday <= 1);
    assert(a.sunset >= 0 && a.sunset <= 1);
    assert(a.night >= 0 && a.night <= 1);
    assert(a.midday >= prevMidday, `Midday must increase monotonically (step ${i})`);
    assert(a.sunset >= prevSunset, `Sunset must increase monotonically (step ${i})`);
    assert(a.night >= prevNight, `Night must increase monotonically (step ${i})`);
    prevMidday = a.midday;
    prevSunset = a.sunset;
    prevNight = a.night;
  }
  console.log("✓ Monotonic continuity across 100 scroll steps passed");
}

// 9. Reduced-motion mode test
{
  const rmDay = computeLayerAlphas(0.1, true);
  assert.strictEqual(rmDay.midday, 0);
  const rmNight = computeLayerAlphas(0.9, true);
  assert.strictEqual(rmNight.night, 1);
  console.log("✓ Reduced-motion mode passed");
}

console.log("ALL GEMINI DAY-TO-NIGHT SCROLL TESTS PASSED SUCCESSFULLY!");

