import { initSync, js_get_collateral, js_verify } from '@phala/dcap-qvl-web';
import wasmB64 from '@phala/dcap-qvl-web/dcap-qvl-web_bg.wasm';
let ready = false;
const init = () => { if (!ready) { initSync({ module: Uint8Array.from(atob(wasmB64), (c) => c.charCodeAt(0)) }); ready = true; } };
// Intel TDX quote verification (Phala dcap-qvl, Rust compiled to WASM). Collateral comes from a CORS-enabled PCCS;
// it is signed by Intel and checked by verify(), so the mirror is only transport. Split so callers can tell an
// unavailable service (collateral) from invalid evidence (verify).
export async function collateral(quoteBytes, pccsUrl) { init(); return js_get_collateral(pccsUrl, quoteBytes); }
export function verify(quoteBytes, coll) { init(); return js_verify(quoteBytes, coll, BigInt(Math.floor(Date.now() / 1000))); }
