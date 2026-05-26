import {
  ScoreRecorded as ScoreRecordedEvent,
  AgentScoreUpdated as AgentScoreUpdatedEvent,
  JudgeScoreUpdated as JudgeScoreUpdatedEvent,
  ValidationRequest as ValidationRequestEvent,
  ValidationResponse as ValidationResponseEvent,
} from "../generated/ValidationRegistry/ValidationRegistry"
import {
  ValidationEvent,
  AgentScore,
  JudgeScore,
  ValidationRequestEvent as ValidationRequestEntity,
  ValidationResponseEvent as ValidationResponseEntity,
  AgentHashLookup,
} from "../generated/schema"

export function handleScoreRecorded(event: ScoreRecordedEvent): void {
  // agentId and taskId are non-indexed strings — directly accessible
  let entity = new ValidationEvent(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.agentId = event.params.agentId
  entity.taskId = event.params.taskId
  entity.score = event.params.score
  entity.mode = event.params.mode
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleAgentScoreUpdated(event: AgentScoreUpdatedEvent): void {
  // agentId is an indexed string — we receive the keccak256 hash, resolve via lookup
  let lookup = AgentHashLookup.load(event.params.agentId)
  let agentId = lookup != null ? lookup.agentId : event.params.agentId.toHexString()

  let score = AgentScore.load(agentId)
  if (score == null) score = new AgentScore(agentId)
  score.averageScore = event.params.averageScore
  score.totalTasks = event.params.totalTasks
  score.blockNumber = event.block.number
  score.blockTimestamp = event.block.timestamp
  score.transactionHash = event.transaction.hash
  score.save()
}

export function handleJudgeScoreUpdated(event: JudgeScoreUpdatedEvent): void {
  // judgeWallet is an indexed address — value type, always recoverable
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
  entity.agentTokenId = event.params.agentId
  entity.requestURI = event.params.requestURI
  entity.requestHash = event.params.requestHash
  entity.blockNumber = event.block.number
  entity.blockTimestamp = event.block.timestamp
  entity.transactionHash = event.transaction.hash
  entity.save()
}

export function handleValidationResponse(event: ValidationResponseEvent): void {
  let entity = new ValidationResponseEntity(
    event.transaction.hash.concatI32(event.logIndex.toI32())
  )
  entity.validatorAddress = event.params.validatorAddress
  entity.agentTokenId = event.params.agentId
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
