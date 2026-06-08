#!/bin/bash
if [ -z "$1" ]; then
  echo "Usage: ./switch-env.sh v1|v2"
  exit 1
fi
if [ ! -f ".env.testnet-$1" ]; then
  echo "Error: .env.testnet-$1 not found"
  exit 1
fi
cp ".env.testnet-$1" .env
echo "Switched to env: testnet-$1"
