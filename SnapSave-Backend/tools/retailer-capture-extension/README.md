# SnapSave retailer toolbar capture

This small Manifest V3 extension runs the existing `export_catalogue_capture.js` only when the user clicks its toolbar button on a supported public retailer page. It uses `activeTab` and `scripting`; there are no persistent host permissions, background polling, cookie access, stored credentials, network interception or automatic uploads. The exporter requests the current site's public robots policy without credentials and exports product-card markup only.

Build with the project Python: `python SnapSave-Backend/tools/retailer-capture-extension/build.py`. Output is `dist/`, including an unpacked extension and a ZIP containing just its three runtime files. The build shares the existing exporter instead of maintaining a second parser/capture implementation.

Installation requires explicit approval because an extension gains access to the clicked tab. Once approved, use Edge's Extensions page, Developer mode, Load unpacked, and select `dist/`. Do not turn off browser security checks. This helper has not been published to the Edge store.

1. In a pending/reviewing SnapSave management ticket, click **Copy research context**.
2. Open the retailer's public catalogue and select that customer's delivery area using the retailer's normal interface. If precise-address or location consent is needed, resolve it explicitly. Wait for products to reload.
3. Click **SnapSave Retailer Capture** in the toolbar. Paste the context into the prompt and confirm the postcode only after checking it. A detected postcode mismatch stops capture.
4. Import the downloaded JSON into the same ticket within 15 minutes. Capture/import never sends a payable quote automatically. Staff must still verify pack, availability, serviceability and checkout fees.

An **OK** badge means a capture was downloaded, not that products are orderable. An **!** badge and toolbar tooltip explain a stopped capture. Missing markup, failed policy access, oversized evidence or a changed location stop the operation. If robots retrieval itself is blocked, the extension stops too; browser rendering success is not a guarantee that this extra request will succeed. Do not repeatedly click or try to evade a retailer challenge.

Official references: [temporary activeTab access](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab), [scripting API](https://developer.chrome.com/docs/extensions/reference/api/scripting), [Edge local installation](https://learn.microsoft.com/en-us/microsoft-edge/extensions/getting-started/extension-sideloading).
