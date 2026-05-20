# Setup Reference

Before running any play, open `setup_reference.html` in your browser and fill in your values as you collect them. Keep it open on a second monitor throughout setup — every notebook Cell 1 and every deploy command maps directly to values in this reference.

## How to use

1. Download `setup_reference.html` from this folder
2. Open it in any browser — double-click the file, no server needed
3. Fill in values as you collect them during setup
4. Use the copy button next to each field to grab values instantly
5. Values save automatically to your browser and persist between sessions

---

## Where to find each value

**Tableau**

| Field | Where to find it |
|-------|-----------------|
| Pod hostname | First part of your Tableau Cloud URL e.g. `10ay.online.tableau.com` |
| Site contentUrl slug | The slug in your Tableau URL after `/site/` — leave blank for Tableau Server default site |
| PAT name | Tableau Cloud → your avatar → Account Settings → Personal Access Tokens → name of your PAT |
| Site ID | Returned automatically after authenticating in any notebook — copy it from the Cell 2 output |
| Datasource LUID | Open the datasource in Tableau Cloud — the **numeric ID** in the URL e.g. `114001783`. Not a UUID. |

**Azure**

| Field | Where to find it |
|-------|-----------------|
| Subscription ID | Azure Portal → Subscriptions → copy the **GUID** e.g. `f108977f-...` — not the display name |
| Resource group | Azure Portal → Resource Groups → your resource group name |
| Logic App name | The name you choose when deploying e.g. `tableau-vds-logic-app` |
| Key Vault name | Azure Portal → Key Vaults → your vault name |
| Key Vault secret name | The name you gave the secret when storing your Tableau PAT |
| Key Vault URL | Auto-built from the Key Vault name — no need to look this up |
| Logic App trigger URL | Logic App → designer → When an HTTP request is received trigger → HTTP POST URL (after deployment) |

**Fabric**

| Field | Where to find it |
|-------|-----------------|
| Workspace ID | Fabric workspace URL — the GUID after `/groups/` |
| Data lakehouse name | The display name you gave your data lakehouse e.g. `h1_ultrastore` |
| Metadata lakehouse name | The display name you gave your metadata lakehouse e.g. `Metadata_Lakehouse` |
| Data lakehouse ID | Auto-resolved by Play 4. Or: Fabric portal → lakehouse → Settings → copy the ID |

---

## Play 1 — Auto-generated deploy command

The Setup Reference auto-builds the full Play 1 deployment command sequence from your values. Once all required fields are filled in, copy the generated command block from the bottom of the page and paste it directly into Azure Cloud Shell.

**Required fields for the deploy command:**
- Subscription ID (GUID format)
- Resource group
- Logic App name
- Key Vault name
- Key Vault secret name
- Tableau pod hostname
- Tableau site contentUrl slug
- Tableau PAT name
- Datasource LUID

---

## Prerequisites checklist

Before starting the plays, confirm:

**Tableau**
- [ ] Tableau Cloud or Server 2025.1+ (VDS API required for Plays 1, 3, and 4)
- [ ] Creator license on the Tableau site
- [ ] PAT created by a user with **Site Administrator** role — a non-admin PAT returns partial inventory and respects RLS
- [ ] PAT expiration set to maximum (up to 1 year on Tableau Cloud)

**Azure**
- [ ] Key Vault created with PAT secret stored
- [ ] Key Vault networking set to allow trusted Microsoft services
- [ ] Azure AI Foundry project with GPT-4o deployed (Play 1 only)

**Fabric**
- [ ] Fabric workspace created
- [ ] `Metadata_Lakehouse` created (Play 2, 3, 4)
- [ ] Data lakehouse created e.g. `h1_ultrastore` (Plays 3, 4)
- [ ] Fabric workspace managed identity granted **Key Vault Secrets User** on the Key Vault (Plays 2, 3, 4)
- [ ] Fabric admin setting **"Service principals can use Fabric APIs"** enabled (Play 4)
