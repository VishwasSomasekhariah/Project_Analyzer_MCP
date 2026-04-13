# FROM python:3.12.8

# WORKDIR /opt/genpod

# COPY . .

# RUN apt-get update && apt-get install -y \
#     make \
#     less \
#     sqlite3 \
#     universal-ctags \
#     wget \
#     unzip \
#     tini \
#     && pip install -r requirements.txt

# # Install git and clone the test repo into /opt/booking-modular-monolith
# RUN apt-get update && apt-get install -y git && \
#     git clone https://github.com/meysamhadeli/booking-modular-monolith.git /opt/booking-modular-monolith && \
#     apt-get remove -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*


# # Install .NET SDK (required for OmniSharp)
# RUN wget https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O packages-microsoft-prod.deb && \
#     dpkg -i packages-microsoft-prod.deb && \
#     apt-get update && \
#     apt-get install -y dotnet-sdk-9.0

# RUN apt-get install -y libc6 libgcc-s1 libgssapi-krb5-2 libicu72 libssl3 libstdc++6 zlib1g

# # Download and install OmniSharp
# RUN mkdir -p /opt/omnisharp && \
#     wget https://github.com/OmniSharp/omnisharp-roslyn/releases/latest/download/omnisharp-linux-x64-net6.0.zip && \
#     unzip omnisharp-linux-x64-net6.0.zip -d /opt/omnisharp && \
#     chmod +x /opt/omnisharp/OmniSharp && \
#     rm omnisharp-linux-x64-net6.0.zip

# ENV PATH="/opt/omnisharp:${PATH}"

# ENTRYPOINT ["/usr/bin/tini", "--"]

# # Start the MCP server (adjust if you use HTTP/SSE)
# CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8001"]
FROM python:3.12.8

WORKDIR /opt/genpod

# Now copy the MCP server code (after CLI is installed)
COPY . .

# Install CLI in editable mode
RUN pip install --upgrade pip setuptools && \
    pip install -e ./project_analyzer_cli && \
    pip install -r requirements.txt

# Install system dependencies and tools
RUN apt-get update && apt-get install -y \
    make \
    less \
    sqlite3 \
    universal-ctags \
    wget \
    unzip \
    tini

# Install git and clone the test repo into /opt/booking-modular-monolith
RUN apt-get update && apt-get install -y git && \
    git clone https://github.com/meysamhadeli/booking-modular-monolith.git /opt/booking-modular-monolith && \
    apt-get remove -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Install .NET SDK (required for OmniSharp)
RUN wget https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    apt-get update && \
    apt-get install -y dotnet-sdk-9.0

RUN apt-get install -y libc6 libgcc-s1 libgssapi-krb5-2 libicu72 libssl3 libstdc++6 zlib1g

# Download and install OmniSharp
RUN mkdir -p /opt/omnisharp && \
    wget https://github.com/OmniSharp/omnisharp-roslyn/releases/latest/download/omnisharp-linux-x64-net6.0.zip && \
    unzip omnisharp-linux-x64-net6.0.zip -d /opt/omnisharp && \
    chmod +x /opt/omnisharp/OmniSharp && \
    rm omnisharp-linux-x64-net6.0.zip

ENV PATH="/opt/omnisharp:${PATH}"
ENV PYTHONPATH=/opt/genpod
# No CMD/ENTRYPOINT: you will run server/tester manually in the dev container
