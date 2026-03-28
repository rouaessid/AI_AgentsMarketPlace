const { buildModule } = require("@nomicfoundation/hardhat-ignition/modules");
module.exports = buildModule("IdentityRegistryModule", (m) => {
  const registry = m.contract("IdentityRegistry");
  return { registry };
});
