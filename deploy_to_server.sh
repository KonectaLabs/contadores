#!/bin/bash
cd "$(dirname "$0")"
ssh -p 5389 root@149.50.136.121 'bash /root/deploy_contadores.sh'
