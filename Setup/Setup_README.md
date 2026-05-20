# Setup Reference

Before running any play, open `setup_reference.html` in your browser and fill in your values as you collect them. Keep it open on a second monitor or second screen throughout the setup process — every notebook Cell 1 maps directly to values in this reference.

## How to use

1. Download `setup_reference.html` from this folder
2. Open it in any browser (Chrome, Edge, Safari — no server needed, just double-click the file)
3. Fill in values as you collect them during setup
4. Use the copy button next to each field to grab values when filling in notebook Cell 1s
5. Values save automatically to your browser — they'll still be there if you close and reopen

## Where to find each value

**Tableau**

| Field | Where to find it |
|-------|-----------------|
| Pod hostname | First part of your Tableau Cloud URL e.g. `10ay.online.tableau.com` |
| Site contentUrl slug | Your site's URL slug — visible in the browser URL after signing in. Leave blank for Tableau Server default site |
| PAT name | Tableau Cloud → your avatar → Account Settings → Personal Access Tokens |
| Site ID | Returned automatically after authenticating in any notebook — copy it from the Cell 2 output |
| Datasource LUID | Tableau Cloud UI: open the datasource → it's in the URL. Or run Play 1's instructions generator notebook |

**Azure**

| Field | Where to find it |
|-------|-----------------|
| Subscription ID | Azure Portal → Subscriptions |
| Resource group | Azure Portal → Resource Groups |
| Key Vault name | Azure Portal → Key Vaults → your vault name |
| Key Vault secret name | The name you gave the secret when storing your Tableau PAT |
| Key Vault URL | Auto-built from the Key Vault name — no need to look this up |
| Logic App trigger URL | Logic App → designer → When an HTTP request is received trigger → HTTP POST URL (Play 1 Step 5) |

**Fabric**

| Field | Where to find it |
|-------|-----------------|
| Workspace ID | Fabric workspace URL — the GUID after `/groups/` |
| Data lakehouse name | The display name you gave your data lakehouse e.g. `h1_ultrastore` |
| Metadata lakehouse name | The display name you gave your metadata lakehouse e.g. `Metadata_Lakehouse` |
| Data lakehouse ID | Auto-resolved by Play 4. Or: Fabric portal → lakehouse → Settings → copy the ID |

## Prerequisites checklist

Before starting the plays, confirm:

- [ ] Tableau Cloud or Server 2025.1+ (VDS API required for Plays 3 and 4)
- [ ] Creator license on the Tableau site
- [ ] PAT created by a user with **Site Administrator** role
- [ ] PAT secret stored in Azure Key Vault
- [ ] Fabric workspace created with `Metadata_Lakehouse` and data lakehouse
- [ ] Fabric workspace managed identity granted **Key Vault Secrets User** on the Key Vault
- [ ] Fabric admin setting **"Service principals can use Fabric APIs"** enabled
