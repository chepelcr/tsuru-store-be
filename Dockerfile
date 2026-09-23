FROM public.ecr.aws/lambda/python:3.9

# arm64 like every Tsuru Lambda; the wkhtmltopdf RPM follows buildx's TARGETARCH.
ARG TARGETARCH=arm64

# UTF-8 configuration
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Install wkhtmltopdf dependencies and wkhtmltopdf itself (AL2 uses yum)
RUN yum -y swap openssl-snapsafe-libs openssl-libs \
    && yum -y install wget fontconfig freetype libX11 libXext libXrender libjpeg-turbo libpng \
    && case "$TARGETARCH" in arm64) RPM_ARCH=aarch64 ;; amd64) RPM_ARCH=x86_64 ;; *) echo "unsupported $TARGETARCH"; exit 1 ;; esac \
    && wget -q https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.amazonlinux2.${RPM_ARCH}.rpm -O /tmp/wkhtmltox.rpm \
    && yum -y install /tmp/wkhtmltox.rpm \
    && rm -f /tmp/wkhtmltox.rpm \
    && yum clean all \
    && wkhtmltopdf --version

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

# Copy only the application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Lambda handler
CMD ["app.main.lambda_handler"]

