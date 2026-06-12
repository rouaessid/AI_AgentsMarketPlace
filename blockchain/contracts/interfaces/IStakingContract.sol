// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

interface IStakingContract {
    function isEligibleProvider(address agent) external view returns (bool);
    function isEligibleJudge   (address agent) external view returns (bool);
    function isLocked          (address agent) external view returns (bool);
    function lockStake  (address agent, uint256 duration) external;
    function unlockStake(address agent) external;
    function slashProvider(address agent) external returns (uint256);
    function slashJudge   (address agent) external returns (uint256);
}
