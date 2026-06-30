# Lifey Location

An iOS companion that records location on-device, keeps an encrypted-at-rest iOS app queue, and uploads batches to Lifey whenever the Mac is reachable through Tailscale.

It is deliberately independent of Traccar. The phone never loses a point because Lifey is offline: delivery retries after the next location event or app launch.

## Run it

1. Open `LifeyLocation.xcodeproj` in Xcode.
2. Select your Personal Team under **Signing & Capabilities** and use your own bundle identifier.
3. Connect your iPhone, select it as the run destination, and press Run.
4. In Lifey on the Mac, create a mobile collector token, then enter the Mac's stable Tailscale DNS address and that token in the app.
5. Grant **Always Allow** location permission. Turn on tracking in the companion app.

The tracking mode uses iOS significant-change monitoring plus normal location updates while moving. iOS ultimately controls background scheduling, so this is automatic collection, not a promise of an exact ten-minute cadence.
