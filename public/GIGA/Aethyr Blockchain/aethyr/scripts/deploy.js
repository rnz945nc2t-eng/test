// scripts/deploy.js — AYR Minimal Test Deploy
//
// Test cases:
//   1. wETH bridge  — bridgeIn mints wETH on AYR → bridgeOut burns it
//   2. Native AYR   — chain native currency, staking, direct transfers
//
// Oracle is real — node process pushes live prices via setPrices()
// No mock values, no hardcoded prices.

const { ethers } = require('hardhat');
const fs   = require('fs');
const path = require('path');

async function main() {
  const [deployer] = await ethers.getSigners();
  const chainId    = (await ethers.provider.getNetwork()).chainId;

  console.log(`\n🚀 AETHYR — Minimal Test Deploy`);
  console.log(`   Deployer : ${deployer.address}`);
  console.log(`   Chain ID : ${chainId}`);
  console.log(`   Balance  : ${ethers.formatEther(await ethers.provider.getBalance(deployer.address))} AYR\n`);

  // 1. AYRToken
  console.log('1. AYRToken...');
  const ayr = await (await ethers.getContractFactory('AYRToken')).deploy();
  await ayr.waitForDeployment();
  const ayrAddr = await ayr.getAddress();
  console.log(`   ✅ ${ayrAddr}`);

  // 2. UTXORegistry
  console.log('2. UTXORegistry...');
  const utxo = await (await ethers.getContractFactory('UTXORegistry')).deploy(deployer.address);
  await utxo.waitForDeployment();
  const utxoAddr = await utxo.getAddress();
  console.log(`   ✅ ${utxoAddr}`);

  // 3. wETH
  console.log('3. WrappedToken (wETH)...');
  const wETH = await (await ethers.getContractFactory('WrappedToken')).deploy(
    'Wrapped Ether', 'wETH', deployer.address
  );
  await wETH.waitForDeployment();
  const wETHAddr = await wETH.getAddress();
  console.log(`   ✅ wETH: ${wETHAddr}`);

  // 4. AYROracle — real prices pushed by node process
  console.log('4. AYROracle (live, node-fed)...');
  const oracle = await (await ethers.getContractFactory('AYROracle')).deploy();
  await oracle.waitForDeployment();
  const oracleAddr = await oracle.getAddress();
  console.log(`   ✅ ${oracleAddr}`);
  console.log(`   ⚠️  Add ORACLE_ADDR=${oracleAddr} to .env so node pushes prices`);

  // 5. SwapRouter
  console.log('5. AYRSwapRouter...');
  const router = await (await ethers.getContractFactory('AYRSwapRouter')).deploy(
    oracleAddr,
    deployer.address,
  );
  await router.waitForDeployment();
  const routerAddr = await router.getAddress();
  console.log(`   ✅ ${routerAddr}`);

  // 6. Staking
  console.log('6. AYRStaking...');
  const staking = await (await ethers.getContractFactory('AYRStaking')).deploy();
  await staking.waitForDeployment();
  const stakingAddr = await staking.getAddress();
  console.log(`   ✅ ${stakingAddr}`);

  // 7. Register wETH in router
  console.log('\n7. Registering wETH in SwapRouter...');
  await (await router.registerAsset('ETH', wETHAddr)).wait();
  console.log(`   ✅ ETH registered`);

  // 8. Set router as wETH minter
  console.log('8. Setting SwapRouter as wETH minter...');
  await (await wETH.setMinter(routerAddr)).wait();
  console.log(`   ✅ wETH.minter = SwapRouter`);

  // 9. Save
  const addresses = {
    network:      'AYR',
    chainId:      Number(chainId),
    deployer:     deployer.address,
    deployedAt:   new Date().toISOString(),
    AYRToken:      ayrAddr,
    UTXO_REGISTRY: utxoAddr,
    wETH:          wETHAddr,
    Oracle:        oracleAddr,
    SwapRouter:    routerAddr,
    AYRStaking:    stakingAddr,
  };

  fs.writeFileSync(
    path.join(__dirname, '../deployed-addresses.json'),
    JSON.stringify(addresses, null, 2)
  );
  console.log(`\n✅ Saved deployed-addresses.json`);

  console.log('\n━━━ Paste into scripts/config.js CONTRACTS: ━━━');
  const skip = new Set(['network','chainId','deployer','deployedAt']);
  Object.entries(addresses)
    .filter(([k]) => !skip.has(k))
    .forEach(([k, v]) => console.log(`  ${k.padEnd(14)}: '${v}',`));

  console.log('\n━━━ Paste into AYR.tsx CONTRACTS: ━━━');
  Object.entries(addresses)
    .filter(([k]) => !skip.has(k))
    .forEach(([k, v]) => console.log(`  ${k.padEnd(14)}: "${v}",`));

  console.log('\n━━━ Add to .env so node pushes live prices: ━━━');
  console.log(`  ORACLE_ADDR=${oracleAddr}`);

  console.log('\n📝 Test plan:');
  console.log('   wETH : relayer calls bridgeIn() → user has wETH on AYR → bridgeOut() to exit');
  console.log('   AYR  : native currency — send directly, stake via staking.stake({ value })');
}

main().catch(e => { console.error(e); process.exit(1); });
