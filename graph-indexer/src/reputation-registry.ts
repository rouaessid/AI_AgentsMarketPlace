import {
  NewFeedback as NewFeedbackEvent,
} from "../generated/ReputationRegistry/ReputationRegistry"
import { ReputationEvent } from "../generated/schema"

export function handleNewFeedback(event: NewFeedbackEvent): void {
  let entity = new ReputationEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.agentId = event.params.agentId
  entity.clientAddress = event.params.clientAddress
  entity.feedbackIndex = event.params.feedbackIndex
  entity.value = event.params.value
  entity.valueDecimals = event.params.valueDecimals
  // tag1 is available as both indexed (hash) and non-indexed — use the non-indexed copy
  entity.tag1 = event.params.tag1
  entity.tag2 = event.params.tag2
  entity.endpoint = event.params.endpoint
  entity.feedbackURI = event.params.feedbackURI
  entity.feedbackHash = event.params.feedbackHash
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}
