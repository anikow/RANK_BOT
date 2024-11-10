# Use an official Python runtime as a parent image
FROM python:3.12-bookworm

# Argument for user creation (for added security)
ARG USERNAME=assistant
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create a non-root user
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && apt-get update \
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# Set up application directory
RUN mkdir -p /opt/app

# Copy all files to the app directory
COPY . /opt/app

# Set ownership and permissions for the app directory
RUN chown -R $USERNAME:$USERNAME /opt/app \
    && chmod -R u+w /opt/app/data

# Switch to the non-root user
USER $USERNAME

# Set working directory
WORKDIR /opt/app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the application
CMD ["python", "bot.py"]
