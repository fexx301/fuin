import { secp256k1 } from '@noble/curves/secp256k1.js';
import { keccak_256 } from '@noble/hashes/sha3.js';
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
const unhex = (h) => Uint8Array.from(h.replace(/^0x/, '').match(/../g).map((x) => parseInt(x, 16)));
// EIP-191 personal_sign recovery: address that signed `text`, or throws on a malformed signature.
export function recoverAddress(text, sigHex) {
  const msg = new TextEncoder().encode(text);
  const prefixed = new Uint8Array([...new TextEncoder().encode('\x19Ethereum Signed Message:\n' + msg.length), ...msg]);
  const h = keccak_256(prefixed);
  const raw = unhex(sigHex);
  if (raw.length !== 65) throw new Error('signature must be 65 bytes');
  let v = raw[64]; if (v >= 27) v -= 27;
  if (v !== 0 && v !== 1) throw new Error('bad recovery byte');
  const sig = secp256k1.Signature.fromBytes(raw.slice(0, 64), 'compact').addRecoveryBit(v);
  const pub = sig.recoverPublicKey(h).toBytes(false);
  return '0x' + hex(keccak_256(pub.slice(1)).slice(12));
}
export { keccak_256 };
// Sign `text` EIP-191-style with a throwaway key (used only to build the live "wrong key" tamper demo).
export function signText(text) {
  const priv = secp256k1.utils.randomSecretKey();
  const msg = new TextEncoder().encode(text);
  const h = keccak_256(new Uint8Array([...new TextEncoder().encode('\x19Ethereum Signed Message:\n' + msg.length), ...msg]));
  const rec = secp256k1.sign(h, priv, { prehash: false, format: 'recovered' });  // [recovery, r, s]
  const out = new Uint8Array(65); out.set(rec.slice(1), 0); out[64] = rec[0] + 27;
  const pub = secp256k1.getPublicKey(priv, false);
  return { signature: '0x' + hex(out), address: '0x' + hex(keccak_256(pub.slice(1)).slice(12)) };
}
