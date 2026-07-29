const video = document.getElementById("video");

const socket = new WebSocket("ws://localhost:8000/ws");

navigator.mediaDevices
.getUserMedia({
    video:true
})
.then(stream=>{

    video.srcObject = stream;

    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    setInterval(()=>{

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        ctx.drawImage(video,0,0);

        canvas.toBlob(blob=>{

            if(socket.readyState===1){

                blob.arrayBuffer().then(buffer=>{

                    socket.send(buffer);

                });

            }

        },"image/jpeg",0.7);

    },100);

});