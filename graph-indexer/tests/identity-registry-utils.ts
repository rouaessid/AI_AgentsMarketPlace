import { newMockEvent } from "matchstick-as"
import { ethereum, BigInt, Address, Bytes } from "@graphprotocol/graph-ts"
import {
  AgentCreated,
  AgentStatusChanged,
  AgentVersionMinted,
  Approval,
  ApprovalForAll,
  BatchMetadataUpdate,
  EIP712DomainChanged,
  MetadataSet,
  MetadataUpdate,
  OwnershipTransferred,
  Transfer
} from "../generated/IdentityRegistry/IdentityRegistry"

export function createAgentCreatedEvent(
  agentId: string,
  tokenId: BigInt,
  owner: Address,
  agentType: i32,
  agentURI: string,
  version: string
): AgentCreated {
  let agentCreatedEvent = changetype<AgentCreated>(newMockEvent())

  agentCreatedEvent.parameters = new Array()

  agentCreatedEvent.parameters.push(
    new ethereum.EventParam("agentId", ethereum.Value.fromString(agentId))
  )
  agentCreatedEvent.parameters.push(
    new ethereum.EventParam(
      "tokenId",
      ethereum.Value.fromUnsignedBigInt(tokenId)
    )
  )
  agentCreatedEvent.parameters.push(
    new ethereum.EventParam("owner", ethereum.Value.fromAddress(owner))
  )
  agentCreatedEvent.parameters.push(
    new ethereum.EventParam(
      "agentType",
      ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(agentType))
    )
  )
  agentCreatedEvent.parameters.push(
    new ethereum.EventParam("agentURI", ethereum.Value.fromString(agentURI))
  )
  agentCreatedEvent.parameters.push(
    new ethereum.EventParam("version", ethereum.Value.fromString(version))
  )

  return agentCreatedEvent
}

export function createAgentStatusChangedEvent(
  agentId: string,
  oldStatus: i32,
  newStatus: i32
): AgentStatusChanged {
  let agentStatusChangedEvent = changetype<AgentStatusChanged>(newMockEvent())

  agentStatusChangedEvent.parameters = new Array()

  agentStatusChangedEvent.parameters.push(
    new ethereum.EventParam("agentId", ethereum.Value.fromString(agentId))
  )
  agentStatusChangedEvent.parameters.push(
    new ethereum.EventParam(
      "oldStatus",
      ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(oldStatus))
    )
  )
  agentStatusChangedEvent.parameters.push(
    new ethereum.EventParam(
      "newStatus",
      ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(newStatus))
    )
  )

  return agentStatusChangedEvent
}

export function createAgentVersionMintedEvent(
  agentId: string,
  newTokenId: BigInt,
  previousTokenId: BigInt,
  agentURI: string,
  version: string
): AgentVersionMinted {
  let agentVersionMintedEvent = changetype<AgentVersionMinted>(newMockEvent())

  agentVersionMintedEvent.parameters = new Array()

  agentVersionMintedEvent.parameters.push(
    new ethereum.EventParam("agentId", ethereum.Value.fromString(agentId))
  )
  agentVersionMintedEvent.parameters.push(
    new ethereum.EventParam(
      "newTokenId",
      ethereum.Value.fromUnsignedBigInt(newTokenId)
    )
  )
  agentVersionMintedEvent.parameters.push(
    new ethereum.EventParam(
      "previousTokenId",
      ethereum.Value.fromUnsignedBigInt(previousTokenId)
    )
  )
  agentVersionMintedEvent.parameters.push(
    new ethereum.EventParam("agentURI", ethereum.Value.fromString(agentURI))
  )
  agentVersionMintedEvent.parameters.push(
    new ethereum.EventParam("version", ethereum.Value.fromString(version))
  )

  return agentVersionMintedEvent
}

export function createApprovalEvent(
  owner: Address,
  approved: Address,
  tokenId: BigInt
): Approval {
  let approvalEvent = changetype<Approval>(newMockEvent())

  approvalEvent.parameters = new Array()

  approvalEvent.parameters.push(
    new ethereum.EventParam("owner", ethereum.Value.fromAddress(owner))
  )
  approvalEvent.parameters.push(
    new ethereum.EventParam("approved", ethereum.Value.fromAddress(approved))
  )
  approvalEvent.parameters.push(
    new ethereum.EventParam(
      "tokenId",
      ethereum.Value.fromUnsignedBigInt(tokenId)
    )
  )

  return approvalEvent
}

export function createApprovalForAllEvent(
  owner: Address,
  operator: Address,
  approved: boolean
): ApprovalForAll {
  let approvalForAllEvent = changetype<ApprovalForAll>(newMockEvent())

  approvalForAllEvent.parameters = new Array()

  approvalForAllEvent.parameters.push(
    new ethereum.EventParam("owner", ethereum.Value.fromAddress(owner))
  )
  approvalForAllEvent.parameters.push(
    new ethereum.EventParam("operator", ethereum.Value.fromAddress(operator))
  )
  approvalForAllEvent.parameters.push(
    new ethereum.EventParam("approved", ethereum.Value.fromBoolean(approved))
  )

  return approvalForAllEvent
}

export function createBatchMetadataUpdateEvent(
  _fromTokenId: BigInt,
  _toTokenId: BigInt
): BatchMetadataUpdate {
  let batchMetadataUpdateEvent = changetype<BatchMetadataUpdate>(newMockEvent())

  batchMetadataUpdateEvent.parameters = new Array()

  batchMetadataUpdateEvent.parameters.push(
    new ethereum.EventParam(
      "_fromTokenId",
      ethereum.Value.fromUnsignedBigInt(_fromTokenId)
    )
  )
  batchMetadataUpdateEvent.parameters.push(
    new ethereum.EventParam(
      "_toTokenId",
      ethereum.Value.fromUnsignedBigInt(_toTokenId)
    )
  )

  return batchMetadataUpdateEvent
}

export function createEIP712DomainChangedEvent(): EIP712DomainChanged {
  let eip712DomainChangedEvent = changetype<EIP712DomainChanged>(newMockEvent())

  eip712DomainChangedEvent.parameters = new Array()

  return eip712DomainChangedEvent
}

export function createMetadataSetEvent(
  tokenId: BigInt,
  indexedKey: string,
  metadataKey: string,
  metadataValue: Bytes
): MetadataSet {
  let metadataSetEvent = changetype<MetadataSet>(newMockEvent())

  metadataSetEvent.parameters = new Array()

  metadataSetEvent.parameters.push(
    new ethereum.EventParam(
      "tokenId",
      ethereum.Value.fromUnsignedBigInt(tokenId)
    )
  )
  metadataSetEvent.parameters.push(
    new ethereum.EventParam("indexedKey", ethereum.Value.fromString(indexedKey))
  )
  metadataSetEvent.parameters.push(
    new ethereum.EventParam(
      "metadataKey",
      ethereum.Value.fromString(metadataKey)
    )
  )
  metadataSetEvent.parameters.push(
    new ethereum.EventParam(
      "metadataValue",
      ethereum.Value.fromBytes(metadataValue)
    )
  )

  return metadataSetEvent
}

export function createMetadataUpdateEvent(_tokenId: BigInt): MetadataUpdate {
  let metadataUpdateEvent = changetype<MetadataUpdate>(newMockEvent())

  metadataUpdateEvent.parameters = new Array()

  metadataUpdateEvent.parameters.push(
    new ethereum.EventParam(
      "_tokenId",
      ethereum.Value.fromUnsignedBigInt(_tokenId)
    )
  )

  return metadataUpdateEvent
}

export function createOwnershipTransferredEvent(
  previousOwner: Address,
  newOwner: Address
): OwnershipTransferred {
  let ownershipTransferredEvent =
    changetype<OwnershipTransferred>(newMockEvent())

  ownershipTransferredEvent.parameters = new Array()

  ownershipTransferredEvent.parameters.push(
    new ethereum.EventParam(
      "previousOwner",
      ethereum.Value.fromAddress(previousOwner)
    )
  )
  ownershipTransferredEvent.parameters.push(
    new ethereum.EventParam("newOwner", ethereum.Value.fromAddress(newOwner))
  )

  return ownershipTransferredEvent
}

export function createTransferEvent(
  from: Address,
  to: Address,
  tokenId: BigInt
): Transfer {
  let transferEvent = changetype<Transfer>(newMockEvent())

  transferEvent.parameters = new Array()

  transferEvent.parameters.push(
    new ethereum.EventParam("from", ethereum.Value.fromAddress(from))
  )
  transferEvent.parameters.push(
    new ethereum.EventParam("to", ethereum.Value.fromAddress(to))
  )
  transferEvent.parameters.push(
    new ethereum.EventParam(
      "tokenId",
      ethereum.Value.fromUnsignedBigInt(tokenId)
    )
  )

  return transferEvent
}
