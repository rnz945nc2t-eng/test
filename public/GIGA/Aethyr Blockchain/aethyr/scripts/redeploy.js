const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

console.log('🚀 Starting redeployment process...');

try {
  // Run the hardhat deployment script
  console.log('Running hardhat deployment...');
  execSync('npx hardhat run scripts/deploy.js --network ayr', { stdio: 'inherit' });

  // Read the new addresses
  const addressesPath = path.join(__dirname, '../deployed-addresses.json');
  if (!fs.existsSync(addressesPath)) {
    throw new Error('deployed-addresses.json not found after deployment.');
  }

  const addresses = JSON.parse(fs.readFileSync(addressesPath, 'utf8'));
  console.log('Loaded new addresses:', addresses);

  // Update scripts/config.js
  const configPath = path.join(__dirname, 'config.js');
  let configContent = fs.readFileSync(configPath, 'utf8');

  // Replace addresses in config.js
  configContent = configContent.replace(/AYR:\s*'0x[a-fA-F0-9]{40}'/, `AYR:    '${addresses.AYRToken}'`);
  configContent = configContent.replace(/wBTC:\s*'0x[a-fA-F0-9]{40}'/, `wBTC:   '${addresses.wBTC}'`);
  configContent = configContent.replace(/wETH:\s*'0x[a-fA-F0-9]{40}'/, `wETH:   '${addresses.wETH}'`);
  configContent = configContent.replace(/wSOL:\s*'0x[a-fA-F0-9]{40}'/, `wSOL:   '${addresses.wSOL}'`);
  configContent = configContent.replace(/wBNB:\s*'0x[a-fA-F0-9]{40}'/, `wBNB:   '${addresses.wBNB}'`);
  configContent = configContent.replace(/wMATIC:\s*'0x[a-fA-F0-9]{40}'/, `wMATIC: '${addresses.wMATIC}'`);
  configContent = configContent.replace(/wARB:\s*'0x[a-fA-F0-9]{40}'/, `wARB:   '${addresses.wARB}'`);
  configContent = configContent.replace(/ORACLE:\s*'0x[a-fA-F0-9]{40}'/, `ORACLE: '${addresses.Oracle}'`);
  configContent = configContent.replace(/ROUTER:\s*'0x[a-fA-F0-9]{40}'/, `ROUTER: '${addresses.SwapRouter}'`);
  configContent = configContent.replace(/STAKING:\s*'0x[a-fA-F0-9]{40}'/, `STAKING:'${addresses.AYRStaking}'`);

  fs.writeFileSync(configPath, configContent, 'utf8');
  console.log('✅ Successfully updated scripts/config.js with new addresses.');

} catch (error) {
  console.error('❌ Redeployment failed:', error.message);
  process.exit(1);
}
