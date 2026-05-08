// scripts/register_ayr.js
// One-off: registers AYRToken in SwapRouter so ETH ↔ AYR swaps work
// Run: npx hardhat run scripts/register_ayr.js --network aethyr (from scripts/ dir)

const { ethers } = require('hardhat');

const ROUTER_ADDR  = '0x51B56bd0be45675A42d9C43480fF4cfC4546F3B8';
const AYR_TOKEN    = '0x6c35781d6D1B99C5B0e3071E98312245f49Fc91B';
const ORACLE_ADDR  = '0xB41dfD5CEa3F237197197202487cad8fd3AeE560';

const ROUTER_ABI = [
  'function registerAsset(string calldata symbol, address tokenContract) external',
];
const ORACLE_ABI = [
  'function setPrices(string[] calldata symbols, uint256[] calldata prices) external',
];

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log(`\nDeployer: ${deployer.address}`);

  // 1. Register AYR in SwapRouter
  const router = new ethers.Contract(ROUTER_ADDR, ROUTER_ABI, deployer);
  console.log('Registering AYR in SwapRouter...');
  await (await router.registerAsset('AYR', AYR_TOKEN)).wait();
  console.log('✅ AYR registered');

  // 2. Seed initial AYR price in oracle ($1.00 = 100_000_000 with 8 decimals)
  // Node will overwrite this with market price once oracle_feeder runs
  const oracle = new ethers.Contract(ORACLE_ADDR, ORACLE_ABI, deployer);
  console.log('Seeding AYR price ($1.00) in oracle...');
  await (await oracle.setPrices(['AYR'], [100_000_000n])).wait();
  console.log('✅ AYR price seeded — node will update with live price shortly');

  console.log('\n✅ Done. ETH ↔ AYR swaps now available.');
}

main().catch(e => { console.error(e); process.exit(1); });
