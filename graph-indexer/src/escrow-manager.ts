import {
  PaymentDeposited as PaymentDepositedEvent,
  PipelinePaymentDeposited as PipelinePaymentDepositedEvent,
  FundsReleased as FundsReleasedEvent,
  ClientRefunded as ClientRefundedEvent,
} from "../generated/EscrowManager/EscrowManager"
import { EscrowEvent } from "../generated/schema"

export function handlePaymentDeposited(event: PaymentDepositedEvent): void {
  let entity = new EscrowEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.taskId = event.params.taskId
  entity.eventType = "PaymentDeposited"
  entity.participant = event.params.client
  entity.amount = event.params.amount
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handlePipelinePaymentDeposited(
  event: PipelinePaymentDepositedEvent
): void {
  let entity = new EscrowEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.taskId = event.params.taskId
  entity.eventType = "PipelinePaymentDeposited"
  entity.participant = event.params.client
  entity.amount = event.params.amount
  entity.participantCount = event.params.participantCount
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleFundsReleased(event: FundsReleasedEvent): void {
  let entity = new EscrowEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.taskId = event.params.taskId
  entity.eventType = "FundsReleased"
  entity.participant = event.params.provider
  entity.amount = event.params.providerAmount
  entity.providerAmount = event.params.providerAmount
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleClientRefunded(event: ClientRefundedEvent): void {
  let entity = new EscrowEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.taskId = event.params.taskId
  entity.eventType = "ClientRefunded"
  entity.participant = event.params.client
  entity.amount = event.params.amount
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}
