import {
  Staked as StakedEvent,
  Unstaked as UnstakedEvent,
  Slashed as SlashedEvent,
} from "../generated/StakingContract/StakingContract"
import { StakeEvent } from "../generated/schema"

export function handleStaked(event: StakedEvent): void {
  let entity = new StakeEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.agent = event.params.agent
  entity.amount = event.params.amount
  entity.eventType = "Staked"
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleUnstaked(event: UnstakedEvent): void {
  let entity = new StakeEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.agent = event.params.agent
  entity.amount = event.params.amount
  entity.eventType = "Unstaked"
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleSlashed(event: SlashedEvent): void {
  let entity = new StakeEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.agent = event.params.agent
  entity.amount = event.params.amount
  entity.eventType = "Slashed"
  entity.reason = event.params.reason
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}
