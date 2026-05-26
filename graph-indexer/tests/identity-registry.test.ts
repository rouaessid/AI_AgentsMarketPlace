import {
  assert,
  describe,
  test,
  clearStore,
  beforeAll,
  afterAll
} from "matchstick-as"
import { BigInt, Address, Bytes } from "@graphprotocol/graph-ts"
import { AgentCreated } from "../generated/schema"
import { AgentCreated as AgentCreatedEvent } from "../generated/IdentityRegistry/IdentityRegistry"
import { handleAgentCreated } from "../src/identity-registry"
import { createAgentCreatedEvent } from "./identity-registry-utils"

// Tests structure (matchstick-as >=0.5.0)
// https://thegraph.com/docs/en/subgraphs/developing/creating/unit-testing-framework/#tests-structure

describe("Describe entity assertions", () => {
  beforeAll(() => {
    let agentId = "Example string value"
    let tokenId = BigInt.fromI32(234)
    let owner = Address.fromString("0x0000000000000000000000000000000000000001")
    let agentType = 123
    let agentURI = "Example string value"
    let version = "Example string value"
    let newAgentCreatedEvent = createAgentCreatedEvent(
      agentId,
      tokenId,
      owner,
      agentType,
      agentURI,
      version
    )
    handleAgentCreated(newAgentCreatedEvent)
  })

  afterAll(() => {
    clearStore()
  })

  // For more test scenarios, see:
  // https://thegraph.com/docs/en/subgraphs/developing/creating/unit-testing-framework/#write-a-unit-test

  test("AgentCreated created and stored", () => {
    assert.entityCount("AgentCreated", 1)

    // 0xa16081f360e3847006db660bae1c6d1b2e17ec2a is the default address used in newMockEvent() function
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "agentId",
      "Example string value"
    )
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "tokenId",
      "234"
    )
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "owner",
      "0x0000000000000000000000000000000000000001"
    )
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "agentType",
      "123"
    )
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "agentURI",
      "Example string value"
    )
    assert.fieldEquals(
      "AgentCreated",
      "0xa16081f360e3847006db660bae1c6d1b2e17ec2a-1",
      "version",
      "Example string value"
    )

    // More assert options:
    // https://thegraph.com/docs/en/subgraphs/developing/creating/unit-testing-framework/#asserts
  })
})
