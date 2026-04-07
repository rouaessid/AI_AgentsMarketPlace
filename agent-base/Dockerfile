# agentmarket/base:v1
FROM python:3.11-slim

COPY mitmproxy-ca-cert.pem /usr/local/share/mitmproxy-ca-cert.pem

# 1. Trust store système + ajouter notre cert
RUN apt-get update -qq && \
    apt-get install -y -qq ca-certificates && \
    cp /usr/local/share/mitmproxy-ca-cert.pem \
       /usr/local/share/ca-certificates/mitmproxy-ca.crt && \
    update-ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. Installer certifi puis patcher avec notre cert
RUN pip install certifi --trusted-host pypi.org \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    --quiet && \
    python -c "\
import certifi; \
ca = open('/usr/local/share/mitmproxy-ca-cert.pem','rb').read(); \
open(certifi.where(),'ab').write(b'\n' + ca); \
size = len(open(certifi.where(),'rb').read()); \
print('certifi patched, bundle size:', size, 'bytes')"

# 3. REQUESTS_CA_BUNDLE → bundle certifi complet (vrais CA + notre cert)
RUN python -c "import certifi; print(certifi.where())" > /tmp/certifi_path.txt && \
    CERTIFI_PATH=$(python -c "import certifi; print(certifi.where())") && \
    echo "certifi at: $CERTIFI_PATH"

ENV REQUESTS_CA_BUNDLE=/usr/local/lib/python3.11/site-packages/certifi/cacert.pem
ENV SSL_CERT_FILE=/usr/local/lib/python3.11/site-packages/certifi/cacert.pem
ENV CURL_CA_BUNDLE=/usr/local/lib/python3.11/site-packages/certifi/cacert.pem
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/mitmproxy-ca-cert.pem

# 4. Vérification
RUN python -c "\
import os; \
bundle = os.environ.get('REQUESTS_CA_BUNDLE'); \
size = len(open(bundle,'rb').read()); \
print('bundle size:', size, 'bytes'); \
assert size > 200000, 'bundle trop petit'; \
print('OK - base image ready')"

WORKDIR /app