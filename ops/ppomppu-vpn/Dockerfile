FROM alpine:3.24
RUN apk add --no-cache openvpn curl ca-certificates iproute2 iptables tinyproxy
CMD ["openvpn", "--config", "/run/vpn/client.ovpn"]
