# SERSFlow systemd deployment (PCES01)

Files for IT to install on the lab server.

## Install paths

| Source (repo) | Target on server |
|---------------|------------------|
| `sersflow.env` | `/etc/sersflow/sersflow.env` |
| `sersflow.service` | `/etc/systemd/system/sersflow.service` |

## Prerequisites

- Application: `/opt/sersflow` (git clone + `.venv` + `pip install -e .`)
- Data: `/var/lib/sersflow/{uploads,data,artifacts}`
- Service user: `sersflow` (group `sersflow`; maintainer `apinilla` in group)

## Enable service (IT, as root)

```bash
sudo mkdir -p /etc/sersflow
sudo cp sersflow.env /etc/sersflow/sersflow.env
sudo chmod 640 /etc/sersflow/sersflow.env
sudo chown root:sersflow /etc/sersflow/sersflow.env

sudo cp sersflow.service /etc/systemd/system/sersflow.service
sudo systemctl daemon-reload
sudo systemctl enable sersflow
sudo systemctl start sersflow
sudo systemctl status sersflow
curl -s http://127.0.0.1:8000/health
```

## Pilot URL

`http://PCES01.ad.icfo.net:8000`
