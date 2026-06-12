// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

interface IEscrowManager {
    function releaseFunds(string calldata taskId, address provider, address[] calldata consensusJudges) external;
    function releaseFundsPipeline(string calldata taskId, address[] calldata consensusJudges) external;
    function refundClient(string calldata taskId) external;
}
