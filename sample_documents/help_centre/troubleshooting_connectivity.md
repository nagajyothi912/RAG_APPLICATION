---
article_id: KB-004
title: Troubleshooting AirFiber connectivity
product_area: troubleshooting
last_updated: 2026-08-10
---

# Troubleshooting AirFiber connectivity

Use this article when the AirFiber connection is down, unstable, or slower than the subscribed plan.

## Router LED status reference

The status LED on the front of the AirFiber ONT reports the state of the fiber line.

| LED colour | Pattern | Meaning | What to do |
| --- | --- | --- | --- |
| Green | Solid | Line is active and authenticated | No action needed |
| Green | Slow blink | Negotiating with the exchange | Wait up to 3 minutes |
| Red | Solid | No optical signal reaching the ONT | Check the fiber cable for sharp bends, then raise a Line Fault ticket |
| Red | Blinking | Fiber cut detected between the home and the exchange | Raise a Line Fault ticket; a field engineer visit is required |
| Orange | Solid | Authenticated but no WAN IP assigned | Power-cycle the ONT for 30 seconds |
| Orange | Blinking | Firmware upgrade in progress | Do not power off; wait 10 minutes |
| Off | — | No power to the ONT | Check the adapter and wall socket |

## Error codes

The AirFiber app shows an error code when a session cannot be established.

| Code | Meaning | Resolution | Escalate after |
| --- | --- | --- | --- |
| AF-401 | Credentials rejected by the exchange | Re-enter the account ID in the app | 2 attempts |
| AF-408 | Session timed out during handshake | Power-cycle the ONT | 3 attempts |
| AF-503 | Exchange port is oversubscribed | Wait 15 minutes and retry; if it persists, request a port reallocation from support | 1 hour |
| AF-511 | MAC address not whitelisted | Register the router MAC under Account > Devices | Immediately |
| AF-620 | Optical power below -27 dBm | Field engineer visit required; raise a Line Fault ticket | Immediately |

## Slow speed diagnosis

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Slow only in the evening, 7 PM to 11 PM | Exchange port congestion during peak hours | Request a port reallocation; peak congestion is not covered by the speed refund policy |
| Slow on Wi-Fi, full speed on cable | Wi-Fi interference or distance from the router | Move to the 5 GHz band or add a mesh extender |
| Slow on every device at all hours | Plan speed cap or optical degradation | Run three official speed tests, then check the refund policy |
| Speed drops after 2 hours of use | ONT overheating | Move the ONT to a ventilated location away from direct sunlight |

## Official speed tests

An official speed test must be run from the AirFiber app, on a device connected by ethernet cable, with no other device active on the line. Tests run on third-party websites or over Wi-Fi are not accepted as evidence for a refund claim.
