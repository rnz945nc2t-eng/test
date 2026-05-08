require("@nomicfoundation/hardhat-toolbox");
const path = require('path');
const fs   = require('fs');

// Load .env from project root (one level up from scripts/)
require("dotenv").config({ path: path.resolve(__dirname, '../.env') });

const BASE_DIR    = process.env.BASE_DIR || '/home/87CF3011/2777-87';
const KEYSTORE_DIR = path.join(BASE_DIR, 'chaindata', 'keystore');
const PASS_FILE    = path.join(BASE_DIR, '.signerpass');
const AUTHORITY    = (process.env.SIGNER_ADDR || '0xe36e1ac26e81f50442b6b66acfd0b575b9936d3b').toLowerCase();

function resolveKey() {
  // Password lives in .signerpass — same file geth uses via --password flag
  if (!fs.existsSync(PASS_FILE)) {
    throw new Error(`\n❌  Password file not found: ${PASS_FILE}\n`);
  }
  const pass = fs.readFileSync(PASS_FILE, 'utf8').trim();

  // Find keystore file — named signer--<address>
  const files = fs.readdirSync(KEYSTORE_DIR);
  const ksFile = files.find(f => f.toLowerCase().includes(AUTHORITY.replace('0x', '')));
  if (!ksFile) {
    throw new Error(`\n❌  No keystore file found for ${AUTHORITY} in ${KEYSTORE_DIR}\n`);
  }

  const ksPath = path.join(KEYSTORE_DIR, ksFile);
  const { ethers } = require('ethers');
  const json   = fs.readFileSync(ksPath, 'utf8');
  const wallet = ethers.Wallet.fromEncryptedJsonSync(json, pass);
  console.log(`[hardhat] Keystore unlocked — ${wallet.address}`);
  return wallet.privateKey;
}

module.exports = {
  solidity: "0.8.24",
  networks: {
    aethyr: {
      url: process.env.AYR_RPC || "https://rpc.aethyr-global.com",
      chainId: 210078,
      accounts: [resolveKey()],
    }
  }
};
