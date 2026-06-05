#!/bin/bash
CITY="${1:-Moscow}"
curl -s "wttr.in/${CITY}?format=3"
