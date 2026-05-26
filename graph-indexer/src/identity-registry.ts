import { crypto, ByteArray, Bytes } from "@graphprotocol/graph-ts"
import {
  AgentCreated as AgentCreatedEvent,
  AgentStatusChanged as AgentStatusChangedEvent,
  AgentVersionMinted as AgentVersionMintedEvent,
} from "../generated/IdentityRegistry/IdentityRegistry"
import { Agent, AgentHashLookup } from "../generated/schema"

export function handleAgentCreated(event: AgentCreatedEvent): void {
  let agent = new Agent(event.params.agentId)
  agent.tokenId = event.params.tokenId
  agent.owner = event.params.owner
  agent.agentType = event.params.agentType
  agent.agentURI = event.params.agentURI
  agent.version = event.params.version
  agent.status = 0
  agent.blockNumber = event.block.number
  agent.blockTimestamp = event.block.timestamp
  agent.transactionHash = event.transaction.hash
  agent.save()

  // Store hash lookup so handleAgentStatusChanged (indexed string) can resolve it
  let hashBytes = Bytes.fromByteArray(crypto.keccak256(ByteArray.fromUTF8(event.params.agentId)))
  let lookup = new AgentHashLookup(hashBytes)
  lookup.agentId = event.params.agentId
  lookup.save()
}

export function handleAgentStatusChanged(event: AgentStatusChangedEvent): void {
  // agentId is an indexed string in the event — The Graph gives us the keccak256 hash
  let lookup = AgentHashLookup.load(event.params.agentId)
  if (lookup == null) return
  let agent = Agent.load(lookup.agentId)
  if (agent == null) return
  agent.status = event.params.newStatus
  agent.blockNumber = event.block.number
  agent.blockTimestamp = event.block.timestamp
  agent.transactionHash = event.transaction.hash
  agent.save()
}

export function handleAgentVersionMinted(event: AgentVersionMintedEvent): void {
  // agentId is non-indexed here — we get the original string directly
  let agent = Agent.load(event.params.agentId)
  if (agent == null) return
  agent.tokenId = event.params.newTokenId
  agent.agentURI = event.params.agentURI
  agent.version = event.params.version
  agent.blockNumber = event.block.number
  agent.blockTimestamp = event.block.timestamp
  agent.transactionHash = event.transaction.hash
  agent.save()
}
