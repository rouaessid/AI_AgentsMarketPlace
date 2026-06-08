import {
  ScoreRecorded as ScoreRecordedEvent,
  JudgeScoreUpdated as JudgeScoreUpdatedEvent,
  ValidationRequest as ValidationRequestEvent,
  ValidationResponse as ValidationResponseEvent,
  HoneypotPassed as HoneypotPassedEvent,
  HoneypotFailed as HoneypotFailedEvent,
} from "../generated/ValidationRegistry/ValidationRegistry"
import {
  ValidationEvent,
  JudgeScore,
  ValidationRequestEvent as ValidationRequestEntity,
  ValidationResponseEvent as ValidationResponseEntity,
  JudgeHoneypotStats,
  HoneypotResultEvent,
} from "../generated/schema"
import { BigInt } from "@graphprotocol/graph-ts"

export function handleScoreRecorded(event: ScoreRecordedEvent): void {
  let entity = new ValidationEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.tokenId = event.params.tokenId
  entity.taskId = event.params.taskId
  entity.score = event.params.score
  entity.mode = event.params.mode
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleJudgeScoreUpdated(event: JudgeScoreUpdatedEvent): void {
  let score = JudgeScore.load(event.params.judgeWallet)
  if (score == null) score = new JudgeScore(event.params.judgeWallet)
  score.agreementRate = event.params.agreementRate
  score.totalVotes = event.params.totalVotes
  score.blockNumber = event.block.number
  score.blockTimestamp = event.block.timestamp
  score.transactionHash = event.transaction.hash
  score.save()
}

export function handleValidationRequest(event: ValidationRequestEvent): void {
  let entity = new ValidationRequestEntity(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.validatorAddress = event.params.validatorAddress
  entity.agentTokenId = event.params.tokenId
  entity.requestURI = event.params.requestURI
  entity.requestHash = event.params.requestHash
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleHoneypotPassed(event: HoneypotPassedEvent): void {
  let judgeTokenId = event.params.judgeTokenId
  let statsId = judgeTokenId.toString()

  let stats = JudgeHoneypotStats.load(statsId)
  if (stats == null) {
    stats = new JudgeHoneypotStats(statsId)
    stats.judgeTokenId  = judgeTokenId
    stats.authorized    = false
    stats.totalPasses   = BigInt.fromI32(0)
    stats.totalFails    = BigInt.fromI32(0)
    stats.lastResultCID = ""
  }
  stats.authorized    = true
  stats.totalPasses   = stats.totalPasses.plus(BigInt.fromI32(1))
  stats.lastResultCID = event.params.resultCID
  stats.blockNumber   = event.block.number
  stats.blockTimestamp = event.block.timestamp
  stats.transactionHash = event.transaction.hash
  stats.save()

  let result = new HoneypotResultEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  result.judgeTokenId = judgeTokenId
  result.passed       = true
  result.resultCID    = event.params.resultCID
  result.blockNumber  = event.block.number
  result.blockTimestamp = event.block.timestamp
  result.transactionHash = event.transaction.hash
  result.save()
}

export function handleHoneypotFailed(event: HoneypotFailedEvent): void {
  let judgeTokenId = event.params.judgeTokenId
  let statsId = judgeTokenId.toString()

  let stats = JudgeHoneypotStats.load(statsId)
  if (stats == null) {
    stats = new JudgeHoneypotStats(statsId)
    stats.judgeTokenId  = judgeTokenId
    stats.authorized    = false
    stats.totalPasses   = BigInt.fromI32(0)
    stats.totalFails    = BigInt.fromI32(0)
    stats.lastResultCID = ""
  }
  stats.authorized    = false
  stats.totalFails    = stats.totalFails.plus(BigInt.fromI32(1))
  stats.lastResultCID = event.params.resultCID
  stats.blockNumber   = event.block.number
  stats.blockTimestamp = event.block.timestamp
  stats.transactionHash = event.transaction.hash
  stats.save()

  let result = new HoneypotResultEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  result.judgeTokenId = judgeTokenId
  result.passed       = false
  result.resultCID    = event.params.resultCID
  result.blockNumber  = event.block.number
  result.blockTimestamp = event.block.timestamp
  result.transactionHash = event.transaction.hash
  result.save()
}

export function handleValidationResponse(event: ValidationResponseEvent): void {
  let entity = new ValidationResponseEntity(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.validatorAddress = event.params.validatorAddress
  entity.agentTokenId = event.params.tokenId
  entity.requestHash = event.params.requestHash
  entity.response = event.params.response
  entity.responseURI = event.params.responseURI
  entity.responseHash = event.params.responseHash
  entity.tag = event.params.tag
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}
