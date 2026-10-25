FROM gradle:8.11.1-jdk17

USER root
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && curl --fail --location --retry 3 \
       https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip \
       -o /tmp/android-tools.zip \
    && unzip -q /tmp/android-tools.zip -d "$ANDROID_HOME/cmdline-tools" \
    && mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" \
    && rm /tmp/android-tools.zip

ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"
RUN yes | sdkmanager --licenses > /dev/null \
    && sdkmanager "platforms;android-35" "build-tools;35.0.0" "platform-tools"

COPY build.sh /usr/local/bin/build-android
RUN sed -i 's/\r$//' /usr/local/bin/build-android \
    && chmod +x /usr/local/bin/build-android
ENTRYPOINT ["/usr/local/bin/build-android"]
